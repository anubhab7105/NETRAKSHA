"""Process-specific monitoring for the Netraksha uvicorn process."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class ProcessSnapshot:
    """Snapshot of a single process's resource usage."""
    pid: int
    name: str
    timestamp: str
    cpu_percent: float
    ram_rss_mb: float
    ram_vms_mb: float
    thread_count: int
    handles: Optional[int] = None         # Windows only
    open_files: Optional[int] = None      # Linux/macOS
    disk_read_mb: Optional[float] = None
    disk_write_mb: Optional[float] = None
    net_sent_mb: Optional[float] = None
    net_recv_mb: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def find_netraksha_pid(process_name: str = "uvicorn") -> Optional[int]:
    """Find the PID of the Netraksha backend process."""
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = proc.info.get("name", "") or ""
                cmdline = " ".join(proc.info.get("cmdline") or [])
                if process_name in name.lower() or process_name in cmdline.lower():
                    # Prefer the one running backend.app
                    if "backend" in cmdline or "app" in cmdline:
                        return proc.info["pid"]
                    return proc.info["pid"]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except ImportError:
        pass
    return None


def snapshot_process(pid: int) -> Optional[ProcessSnapshot]:
    """Take a single snapshot of a process."""
    try:
        import psutil
        from datetime import datetime, timezone
        proc = psutil.Process(pid)
        with proc.oneshot():
            name = proc.name()
            cpu = proc.cpu_percent(interval=0.1)
            mem = proc.memory_info()
            threads = proc.num_threads()
            handles = None
            open_files = None
            try:
                if hasattr(proc, "num_handles"):
                    handles = proc.num_handles()
                else:
                    open_files = len(proc.open_files())
            except Exception:
                pass

            io_read_mb = None
            io_write_mb = None
            try:
                io = proc.io_counters()
                io_read_mb = io.read_bytes / (1024 * 1024)
                io_write_mb = io.write_bytes / (1024 * 1024)
            except Exception:
                pass

        return ProcessSnapshot(
            pid=pid,
            name=name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            cpu_percent=cpu,
            ram_rss_mb=round(mem.rss / (1024 * 1024), 2),
            ram_vms_mb=round(mem.vms / (1024 * 1024), 2),
            thread_count=threads,
            handles=handles,
            open_files=open_files,
            disk_read_mb=round(io_read_mb, 2) if io_read_mb is not None else None,
            disk_write_mb=round(io_write_mb, 2) if io_write_mb is not None else None,
        )
    except Exception:
        return None


class ProcessMonitor:
    """Track a specific process over time."""

    def __init__(self, pid: Optional[int] = None, process_name: str = "uvicorn"):
        self.pid = pid or find_netraksha_pid(process_name)
        self.snapshots: List[ProcessSnapshot] = []

    def take_snapshot(self) -> Optional[ProcessSnapshot]:
        if self.pid is None:
            return None
        snap = snapshot_process(self.pid)
        if snap:
            self.snapshots.append(snap)
        return snap

    def get_summary(self) -> Dict[str, Any]:
        if not self.snapshots:
            return {"status": "NOT_AVAILABLE", "reason": "No process snapshots taken"}
        rams = [s.ram_rss_mb for s in self.snapshots]
        cpus = [s.cpu_percent for s in self.snapshots]
        return {
            "pid": self.pid,
            "sample_count": len(self.snapshots),
            "ram_rss_min_mb": round(min(rams), 2),
            "ram_rss_avg_mb": round(sum(rams) / len(rams), 2),
            "ram_rss_max_mb": round(max(rams), 2),
            "ram_rss_peak_mb": round(max(rams), 2),
            "cpu_avg_pct": round(sum(cpus) / len(cpus), 1),
            "cpu_peak_pct": round(max(cpus), 1),
        }
