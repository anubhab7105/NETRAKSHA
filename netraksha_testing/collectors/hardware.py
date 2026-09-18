"""Hardware information collector.

Detects CPU, RAM, GPU, and disk information using psutil and optional
GPU libraries. Never fabricates values — reports NOT_AVAILABLE clearly.
"""

from __future__ import annotations

import platform
import sys
from typing import Any, Dict, List, Optional

from ..core.models import HardwareInfo, MetricSource

_NOT_AVAIL = "NOT_AVAILABLE"


def _get_cpu_model() -> str:
    """Get CPU model string — platform-specific."""
    try:
        if sys.platform == "win32":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            model, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            return model.strip()
        elif sys.platform == "linux":
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":")[1].strip()
        elif sys.platform == "darwin":
            import subprocess
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True,
            )
            return result.stdout.strip()
    except Exception:
        pass
    return platform.processor() or _NOT_AVAIL


def _get_cpu_temp() -> Optional[float]:
    """CPU temperature in Celsius — only on supported platforms."""
    try:
        import psutil
        temps = psutil.sensors_temperatures()
        if not temps:
            return None
        # Try common sensor names
        for key in ["coretemp", "k10temp", "cpu_thermal", "acpitz"]:
            entries = temps.get(key, [])
            if entries:
                # Return average of core readings
                vals = [e.current for e in entries if e.current is not None]
                if vals:
                    return round(sum(vals) / len(vals), 1)
        # Fallback: first available sensor
        for entries in temps.values():
            vals = [e.current for e in entries if e.current is not None]
            if vals:
                return round(vals[0], 1)
    except Exception:
        pass
    return None


def _get_gpu_info() -> Dict[str, Any]:
    """GPU information via GPUtil, pynvml, or WMI fallback."""
    result = {
        "model": None,
        "vram_mb": None,
        "utilization_pct": None,
        "temperature_c": None,
    }

    # Try GPUtil (NVIDIA)
    try:
        import GPUtil
        gpus = GPUtil.getGPUs()
        if gpus:
            gpu = gpus[0]
            result["model"] = gpu.name
            result["vram_mb"] = gpu.memoryTotal
            result["utilization_pct"] = gpu.load * 100
            result["temperature_c"] = gpu.temperature
            return result
    except ImportError:
        pass
    except Exception:
        pass

    # Try pynvml
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        result["model"] = pynvml.nvmlDeviceGetName(handle).decode("utf-8")
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        result["vram_mb"] = mem.total / (1024 * 1024)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        result["utilization_pct"] = util.gpu
        result["temperature_c"] = pynvml.nvmlDeviceGetTemperature(
            handle, pynvml.NVML_TEMPERATURE_GPU
        )
        pynvml.nvmlShutdown()
        return result
    except ImportError:
        pass
    except Exception:
        pass

    # Windows WMI fallback (model name only)
    if sys.platform == "win32":
        try:
            import subprocess
            cmd = "wmic path win32_VideoController get Name,AdapterRAM /format:csv"
            out = subprocess.check_output(cmd, shell=True, text=True, timeout=5)
            lines = [l.strip() for l in out.splitlines() if l.strip() and "Node" not in l]
            if lines:
                parts = lines[0].split(",")
                if len(parts) >= 3:
                    result["model"] = parts[2].strip() if parts[2].strip() else None
                    try:
                        vram_bytes = int(parts[1])
                        result["vram_mb"] = vram_bytes / (1024 * 1024)
                    except (ValueError, IndexError):
                        pass
        except Exception:
            pass

    return result


def _get_disk_info() -> List[Dict[str, Any]]:
    """Disk partitions with size information."""
    devices = []
    try:
        import psutil
        partitions = psutil.disk_partitions(all=False)
        for part in partitions:
            try:
                usage = psutil.disk_usage(part.mountpoint)
                devices.append({
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "total_gb": round(usage.total / (1024 ** 3), 2),
                    "used_gb": round(usage.used / (1024 ** 3), 2),
                    "free_gb": round(usage.free / (1024 ** 3), 2),
                    "utilization_pct": usage.percent,
                })
            except (PermissionError, OSError):
                pass
    except ImportError:
        pass
    return devices


def collect_hardware() -> Optional[HardwareInfo]:
    """Collect current hardware information snapshot.

    Returns None if psutil is not available.
    All individual fields that cannot be measured are set to None
    with a MetricSource.NOT_AVAILABLE annotation.
    """
    try:
        import psutil
    except ImportError:
        print("[hardware] psutil not installed — hardware metrics unavailable")
        return None

    cpu_model = _get_cpu_model()
    cpu_arch = platform.machine()
    cpu_physical = psutil.cpu_count(logical=False) or 0
    cpu_logical = psutil.cpu_count(logical=True) or 0

    cpu_freq = psutil.cpu_freq()
    cpu_base_freq = round(cpu_freq.min, 1) if cpu_freq and cpu_freq.min else None
    cpu_max_freq = round(cpu_freq.max, 1) if cpu_freq and cpu_freq.max else None
    cpu_util = psutil.cpu_percent(interval=1.0)
    cpu_temp = _get_cpu_temp()

    vm = psutil.virtual_memory()
    ram_total = round(vm.total / (1024 ** 3), 2)
    ram_avail = round(vm.available / (1024 ** 3), 2)
    ram_used = round(vm.used / (1024 ** 3), 2)
    ram_util = vm.percent

    swap = psutil.swap_memory()
    swap_total = round(swap.total / (1024 ** 3), 2)
    swap_used = round(swap.used / (1024 ** 3), 2)

    gpu = _get_gpu_info()
    disk_devices = _get_disk_info()

    total_gb = sum(d["total_gb"] for d in disk_devices)
    avail_gb = sum(d["free_gb"] for d in disk_devices)

    source_notes: Dict[str, MetricSource] = {
        "cpu_temperature": MetricSource.MEASURED if cpu_temp is not None else MetricSource.NOT_AVAILABLE,
        "gpu_model": MetricSource.MEASURED if gpu["model"] else MetricSource.NOT_AVAILABLE,
        "gpu_vram": MetricSource.MEASURED if gpu["vram_mb"] else MetricSource.NOT_AVAILABLE,
        "gpu_utilization": MetricSource.MEASURED if gpu["utilization_pct"] is not None else MetricSource.NOT_AVAILABLE,
        "gpu_temperature": MetricSource.MEASURED if gpu["temperature_c"] is not None else MetricSource.NOT_AVAILABLE,
        "cpu_base_freq": MetricSource.MEASURED if cpu_base_freq else MetricSource.NOT_AVAILABLE,
    }

    return HardwareInfo(
        cpu_model=cpu_model,
        cpu_arch=cpu_arch,
        cpu_physical_cores=cpu_physical,
        cpu_logical_cores=cpu_logical,
        cpu_base_freq_mhz=cpu_base_freq,
        cpu_max_freq_mhz=cpu_max_freq,
        cpu_utilization_pct=cpu_util,
        cpu_temperature_c=cpu_temp,
        ram_total_gb=ram_total,
        ram_available_gb=ram_avail,
        ram_used_gb=ram_used,
        ram_utilization_pct=ram_util,
        swap_total_gb=swap_total,
        swap_used_gb=swap_used,
        gpu_model=gpu["model"],
        gpu_vram_mb=gpu["vram_mb"],
        gpu_utilization_pct=gpu["utilization_pct"],
        gpu_temperature_c=gpu["temperature_c"],
        disk_devices=disk_devices,
        disk_total_gb=total_gb,
        disk_available_gb=avail_gb,
        source_notes=source_notes,
    )
