"""Comparison module to diff two run results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import FrameworkConfig


@dataclass
class DiffRow:
    metric: str
    baseline: Any
    current: Any
    delta: Any
    pct_change: float
    status: str  # "IMPROVED", "REGRESSED", "STABLE", "N/A"


def _compare_numeric(val1: float, val2: float, higher_is_better: bool, threshold_pct: float) -> tuple[float, float, str]:
    delta = val2 - val1
    pct = (delta / abs(val1)) * 100 if val1 != 0 else 0.0
    
    if abs(pct) < threshold_pct:
        status = "STABLE"
    elif (pct > 0 and higher_is_better) or (pct < 0 and not higher_is_better):
        status = "IMPROVED"
    else:
        status = "REGRESSED"
        
    return delta, pct, status


def compare_runs(baseline_path: Path, current_path: Path, cfg: FrameworkConfig) -> List[DiffRow]:
    """Compare two JSON run result files and return a list of diffs."""
    try:
        with open(baseline_path, 'r', encoding='utf-8') as f:
            base = json.load(f)
        with open(current_path, 'r', encoding='utf-8') as f:
            curr = json.load(f)
    except Exception as e:
        print(f"Error loading files for comparison: {e}")
        return []

    diffs: List[DiffRow] = []
    lat_thresh = cfg.threshold("latency_regression_pct") or 10.0
    tp_thresh = cfg.threshold("throughput_regression_pct") or 10.0
    
    # 1. Compare Pipeline Latencies
    base_pipe = next((r for r in base.get("results", []) if r["test_name"] == "pipeline_module_benchmark"), None)
    curr_pipe = next((r for r in curr.get("results", []) if r["test_name"] == "pipeline_module_benchmark"), None)
    
    if base_pipe and curr_pipe:
        b_mets = base_pipe.get("metrics", {})
        c_mets = curr_pipe.get("metrics", {})
        
        for k in b_mets:
            if k.endswith("_warm_avg_ms") and k in c_mets:
                b_val = b_mets[k]
                c_val = c_mets[k]
                if isinstance(b_val, (int, float)) and isinstance(c_val, (int, float)):
                    delta, pct, status = _compare_numeric(b_val, c_val, higher_is_better=False, threshold_pct=lat_thresh)
                    diffs.append(DiffRow(
                        metric=f"Pipeline: {k.replace('_warm_avg_ms', '')} latency (ms)",
                        baseline=round(b_val, 2), current=round(c_val, 2),
                        delta=round(delta, 2), pct_change=round(pct, 1), status=status
                    ))

    # 2. Compare API Throughput & Latency
    base_api = next((r for r in base.get("results", []) if r["test_name"] == "api_health_benchmark"), None)
    curr_api = next((r for r in curr.get("results", []) if r["test_name"] == "api_health_benchmark"), None)
    
    if base_api and curr_api:
        b_mets = base_api.get("metrics", {})
        c_mets = curr_api.get("metrics", {})
        
        if "throughput_rps" in b_mets and "throughput_rps" in c_mets:
            b_val = b_mets["throughput_rps"]
            c_val = c_mets["throughput_rps"]
            delta, pct, status = _compare_numeric(b_val, c_val, higher_is_better=True, threshold_pct=tp_thresh)
            diffs.append(DiffRow(
                metric="API Health: Throughput (RPS)",
                baseline=round(b_val, 1), current=round(c_val, 1),
                delta=round(delta, 1), pct_change=round(pct, 1), status=status
            ))
            
        if "p95_ms" in b_mets and "p95_ms" in c_mets:
            b_val = b_mets["p95_ms"]
            c_val = c_mets["p95_ms"]
            delta, pct, status = _compare_numeric(b_val, c_val, higher_is_better=False, threshold_pct=lat_thresh)
            diffs.append(DiffRow(
                metric="API Health: P95 Latency (ms)",
                baseline=round(b_val, 1), current=round(c_val, 1),
                delta=round(delta, 1), pct_change=round(pct, 1), status=status
            ))

    return diffs
