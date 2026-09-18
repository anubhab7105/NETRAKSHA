"""System resource charts."""

from __future__ import annotations

from typing import Any

from ..core.models import RunResult
from .theme import COLORS, _HAS_MATPLOTLIB, save_chart, setup_theme


def generate_system_charts(run: RunResult, cfg: Any) -> None:
    """Generate CPU, RAM, and Disk I/O charts over time."""
    if not _HAS_MATPLOTLIB or not run.hardware_samples:
        return
        
    import matplotlib.pyplot as plt
    setup_theme()
    dpi = cfg.charts_dpi
    
    samples = run.hardware_samples
    if len(samples) < 2:
        return
        
    x = list(range(len(samples)))
    
    # 1. CPU Usage
    cpus = [s.get("cpu_percent", 0) for s in samples]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(x, cpus, color=COLORS["primary"])
    ax.fill_between(x, cpus, alpha=0.2, color=COLORS["primary"])
    ax.set_title("CPU Utilization Over Time")
    ax.set_ylabel("CPU %")
    ax.set_xlabel("Time (Samples)")
    ax.set_ylim(0, 105)
    ax.grid(True, axis='y')
    save_chart(fig, "sys_cpu", cfg.output_dir, dpi)
    
    # 2. RAM Usage
    rams = [s.get("ram_mb", 0) for s in samples]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(x, rams, color=COLORS["secondary"])
    ax.fill_between(x, rams, alpha=0.2, color=COLORS["secondary"])
    ax.set_title("RAM Usage Over Time")
    ax.set_ylabel("RAM (MB)")
    ax.set_xlabel("Time (Samples)")
    # Don't start y at 0 to see growth better
    min_ram, max_ram = min(rams), max(rams)
    margin = (max_ram - min_ram) * 0.2 or max_ram * 0.1
    ax.set_ylim(max(0, min_ram - margin), max_ram + margin)
    ax.grid(True, axis='y')
    
    # Add leak regression line if available
    if run.memory_analysis and run.memory_analysis.sample_count > 0:
         ma = run.memory_analysis
         warmup = len(samples) - ma.sample_count
         ax.plot(x[warmup:], [ma.baseline_mb + (i * (ma.slope_mb_per_100req / 100)) for i in range(ma.sample_count)],
                 color=COLORS["danger"], linestyle="--", label=f"Trend: {ma.slope_mb_per_100req:.2f} MB/100")
         ax.legend()
         
    save_chart(fig, "sys_ram", cfg.output_dir, dpi)
