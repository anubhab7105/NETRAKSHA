"""Performance charts: latency distributions, breakdowns, load curves."""

from __future__ import annotations

from typing import Any

from ..core.models import RunResult
from .theme import COLORS, _HAS_MATPLOTLIB, save_chart, setup_theme


def generate_performance_charts(run: RunResult, cfg: Any) -> None:
    """Generate pipeline latency breakdowns and API latency distributions."""
    if not _HAS_MATPLOTLIB:
        return
        
    import matplotlib.pyplot as plt
    import numpy as np
    setup_theme()
    dpi = cfg.charts_dpi
    
    # 1. Pipeline Breakdown
    pipe_res = next((r for r in run.results if r.test_name == "pipeline_module_benchmark"), None)
    if pipe_res:
        mods = []
        times = []
        for k, v in pipe_res.metrics.items():
             if k.endswith("_warm_avg_ms") and isinstance(v, (int, float)):
                 mods.append(k.replace("_warm_avg_ms", ""))
                 times.append(v)
                 
        if mods:
             # Sort by time
             sorted_data = sorted(zip(mods, times), key=lambda x: x[1])
             mods = [x[0] for x in sorted_data]
             times = [x[1] for x in sorted_data]
             
             fig, ax = plt.subplots(figsize=(10, 6))
             y_pos = np.arange(len(mods))
             bars = ax.barh(y_pos, times, color=COLORS["primary"])
             ax.set_yticks(y_pos, labels=mods)
             ax.set_xlabel("Latency (ms)")
             ax.set_title("Pipeline Module Average Inference Time")
             
             # Add values on bars
             for i, v in enumerate(times):
                 ax.text(v + (max(times)*0.01), i, f"{v:.1f}ms", va='center', fontweight='bold')
                 
             save_chart(fig, "perf_pipeline_breakdown", cfg.output_dir, dpi)
             
    # 2. API Latency Distribution
    api_res = next((r for r in run.results if r.test_name == "api_health_benchmark"), None)
    if api_res and api_res.samples:
        latencies = [s.duration_ms for s in api_res.samples if s.success]
        if latencies:
             fig, ax = plt.subplots(figsize=(8, 5))
             ax.hist(latencies, bins=min(20, len(latencies)), color=COLORS["info"], alpha=0.8)
             ax.set_title("API Response Time Distribution")
             ax.set_xlabel("Response Time (ms)")
             ax.set_ylabel("Count")
             
             # Add percentiles
             p50, p95 = np.percentile(latencies, [50, 95])
             ax.axvline(p50, color=COLORS["success"], linestyle='dashed', linewidth=2, label=f"P50: {p50:.1f}ms")
             ax.axvline(p95, color=COLORS["warning"], linestyle='dashed', linewidth=2, label=f"P95: {p95:.1f}ms")
             ax.legend()
             
             save_chart(fig, "perf_api_dist", cfg.output_dir, dpi)
