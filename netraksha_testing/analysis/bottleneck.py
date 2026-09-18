"""Analysis package for Netraksha Testing Framework."""

from __future__ import annotations

from typing import List

from ..core.config import FrameworkConfig
from ..core.models import MemoryLeakAnalysis, MetricSource, RunResult


def analyze_memory_growth(samples: List[dict], cfg: FrameworkConfig) -> MemoryLeakAnalysis:
    """Perform linear regression on memory samples to detect leaks.
    
    Ignores the first 20% of samples (warm-up/model loading phase).
    """
    if not samples or len(samples) < 5:
        return MemoryLeakAnalysis(
            baseline_mb=0, min_mb=0, avg_mb=0, max_mb=0,
            slope_mb_per_100req=0, r_squared=0, suspected_leak=False,
            sample_count=len(samples), note="Insufficient samples",
            source=MetricSource.NOT_AVAILABLE
        )
        
    rams = [s.get("ram_mb", 0) for s in samples if s.get("ram_mb") is not None]
    if not rams:
        return MemoryLeakAnalysis(
            baseline_mb=0, min_mb=0, avg_mb=0, max_mb=0,
            slope_mb_per_100req=0, r_squared=0, suspected_leak=False,
            sample_count=0, note="No RAM metrics",
            source=MetricSource.NOT_AVAILABLE
        )
        
    # Drop first 20% to account for lazy loading/warmup
    warmup_idx = int(len(rams) * 0.2)
    stable_rams = rams[warmup_idx:]
    if not stable_rams:
        stable_rams = rams
        
    n = len(stable_rams)
    x = list(range(n))
    y = stable_rams
    
    # Linear regression: y = mx + c
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    
    numer = sum((x_i - mean_x) * (y_i - mean_y) for x_i, y_i in zip(x, y))
    denom = sum((x_i - mean_x) ** 2 for x_i in x)
    
    slope = numer / denom if denom != 0 else 0
    c = mean_y - slope * mean_x
    
    # R-squared
    ss_tot = sum((y_i - mean_y) ** 2 for y_i in y)
    ss_res = sum((y_i - (slope * x_i + c)) ** 2 for x_i, y_i in zip(x, y))
    r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
    
    # Scale slope to MB per 100 samples
    slope_per_100 = slope * 100
    
    threshold = cfg.thresholds.get("memory_leak_slope_mb_per_100req", 0.5)
    
    # Only flag as leak if slope is high AND R-squared is decent (linear fit)
    is_leak = slope_per_100 > threshold and r_squared > 0.5
    
    return MemoryLeakAnalysis(
        baseline_mb=round(rams[0], 2),
        min_mb=round(min(rams), 2),
        avg_mb=round(sum(rams)/len(rams), 2),
        max_mb=round(max(rams), 2),
        slope_mb_per_100req=round(slope_per_100, 3),
        r_squared=round(r_squared, 3),
        suspected_leak=is_leak,
        sample_count=len(rams),
        note=f"Analyzed {n} stable samples (dropped {warmup_idx} warmup)"
    )


def detect_bottlenecks(run: RunResult, cfg: FrameworkConfig) -> List[str]:
    """Automated bottleneck detection based on thresholds."""
    findings = []
    
    # Hardware bottlenecks
    if run.hardware_samples:
        cpus = [s.get("cpu_percent", 0) for s in run.hardware_samples if s.get("cpu_percent") is not None]
        rams = [s.get("ram_percent", 0) for s in run.hardware_samples if s.get("ram_percent") is not None]
        
        if cpus:
            avg_cpu = sum(cpus) / len(cpus)
            thresh = cfg.threshold("cpu_bottleneck_pct") or 80.0
            if avg_cpu > thresh:
                findings.append(f"CPU Bottleneck: Average utilization is {avg_cpu:.1f}% (threshold: {thresh}%)")
                
        if rams:
            max_ram = max(rams)
            thresh = cfg.threshold("ram_bottleneck_pct") or 85.0
            if max_ram > thresh:
                findings.append(f"RAM Bottleneck: Peak utilization reached {max_ram:.1f}% (threshold: {thresh}%)")
                
    # Pipeline latency bottlenecks
    for res in run.results:
        if res.test_name == "pipeline_module_benchmark" and res.status == TestStatus.PASS:
            # Find the slowest module
            slowest = ("", 0.0)
            total = 0.0
            for k, v in res.metrics.items():
                if k.endswith("_warm_avg_ms") and isinstance(v, (int, float)):
                    mod_name = k.replace("_warm_avg_ms", "")
                    total += v
                    if v > slowest[1]:
                        slowest = (mod_name, v)
                        
            if total > 0 and slowest[1] > 0:
                pct = (slowest[1] / total) * 100
                if pct > 40.0:  # If one module takes >40% of time
                    findings.append(f"Pipeline Bottleneck: Module '{slowest[0]}' dominates latency ({slowest[1]:.1f}ms, {pct:.1f}% of total pipeline execution)")
                    
    return findings
