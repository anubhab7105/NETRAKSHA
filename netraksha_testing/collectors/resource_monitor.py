"""Background resource monitor — CPU/RAM/GPU sampling thread.

Runs in a daemon thread at a configurable interval. Designed for
minimal overhead (<1% CPU on most systems at 0.5s interval).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ResourceSample:
    """A single resource usage snapshot."""
    timestamp: str
    cpu_percent: float
    ram_mb: float
    ram_percent: float
    swap_mb: float
    disk_read_mb: Optional[float] = None
    disk_write_mb: Optional[float] = None
    gpu_percent: Optional[float] = None
    gpu_vram_mb: Optional[float] = None
    gpu_temp_c: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ResourceMonitor:
    """Background thread that samples system resource usage.

    Usage::

        samples = []
        monitor = ResourceMonitor(interval_s=0.5, output=samples)
        monitor.start()
        # ... do work ...
        monitor.stop()
        # samples now contains ResourceSample dicts
    """

    def __init__(
        self,
        interval_s: float = 0.5,
        output: Optional[List[Dict[str, Any]]] = None,
    ):
        self.interval_s = interval_s
        self._output = output if output is not None else []
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._prev_disk_io = None
        self._prev_disk_time = None
        self._has_psutil = False
        self._has_gpu = False
        self._overhead_ms: List[float] = []

        try:
            import psutil
            self._has_psutil = True
        except ImportError:
            pass

        try:
            import GPUtil
            self._has_gpu = True
            self._gpu_lib = "gputil"
        except ImportError:
            try:
                import pynvml
                pynvml.nvmlInit()
                self._has_gpu = True
                self._gpu_lib = "pynvml"
            except Exception:
                pass

    def start(self) -> None:
        """Start the background sampling thread."""
        if not self._has_psutil:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._sample_loop,
            daemon=True,
            name="ResourceMonitor",
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop sampling and join the thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=self.interval_s * 3)

    def get_samples(self) -> List[Dict[str, Any]]:
        return list(self._output)

    def get_overhead_ms(self) -> float:
        """Average per-sample measurement overhead in ms."""
        if not self._overhead_ms:
            return 0.0
        return sum(self._overhead_ms) / len(self._overhead_ms)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _sample_loop(self) -> None:
        import psutil
        # Initialize disk IO baseline
        try:
            self._prev_disk_io = psutil.disk_io_counters()
            self._prev_disk_time = time.perf_counter()
        except Exception:
            pass

        while not self._stop_event.is_set():
            t0 = time.perf_counter()
            sample = self._take_sample()
            overhead = (time.perf_counter() - t0) * 1000
            self._overhead_ms.append(overhead)
            self._output.append(sample.to_dict())

            # Sleep for the remainder of the interval
            elapsed = time.perf_counter() - t0
            sleep_time = max(0.0, self.interval_s - elapsed)
            self._stop_event.wait(timeout=sleep_time)

    def _take_sample(self) -> ResourceSample:
        import psutil

        cpu_pct = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        ram_mb = vm.used / (1024 * 1024)
        ram_pct = vm.percent
        swap = psutil.swap_memory()
        swap_mb = swap.used / (1024 * 1024)

        # Disk IO rates
        disk_read_mb = None
        disk_write_mb = None
        try:
            now_io = psutil.disk_io_counters()
            now_time = time.perf_counter()
            if self._prev_disk_io and self._prev_disk_time:
                dt = now_time - self._prev_disk_time
                if dt > 0:
                    disk_read_mb = (now_io.read_bytes - self._prev_disk_io.read_bytes) / (1024 * 1024 * dt)
                    disk_write_mb = (now_io.write_bytes - self._prev_disk_io.write_bytes) / (1024 * 1024 * dt)
            self._prev_disk_io = now_io
            self._prev_disk_time = now_time
        except Exception:
            pass

        # GPU
        gpu_pct = None
        gpu_vram = None
        gpu_temp = None
        if self._has_gpu:
            try:
                if self._gpu_lib == "gputil":
                    import GPUtil
                    gpus = GPUtil.getGPUs()
                    if gpus:
                        gpu_pct = gpus[0].load * 100
                        gpu_vram = gpus[0].memoryUsed
                        gpu_temp = gpus[0].temperature
                elif self._gpu_lib == "pynvml":
                    import pynvml
                    handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    gpu_pct = util.gpu
                    mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    gpu_vram = mem.used / (1024 * 1024)
                    gpu_temp = pynvml.nvmlDeviceGetTemperature(
                        handle, pynvml.NVML_TEMPERATURE_GPU
                    )
            except Exception:
                pass

        return ResourceSample(
            timestamp=datetime.utcnow().isoformat(),
            cpu_percent=round(cpu_pct, 1),
            ram_mb=round(ram_mb, 1),
            ram_percent=round(ram_pct, 1),
            swap_mb=round(swap_mb, 1),
            disk_read_mb=round(disk_read_mb, 3) if disk_read_mb is not None else None,
            disk_write_mb=round(disk_write_mb, 3) if disk_write_mb is not None else None,
            gpu_percent=round(gpu_pct, 1) if gpu_pct is not None else None,
            gpu_vram_mb=round(gpu_vram, 1) if gpu_vram is not None else None,
            gpu_temp_c=round(gpu_temp, 1) if gpu_temp is not None else None,
        )
