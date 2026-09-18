"""Pipeline benchmark suite.

Tests direct Python invocation of all pipeline modules.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List

from ..core.adapters import build_adapters
from ..core.config import FrameworkConfig
from ..core.models import BenchmarkSample, MetricSource, TestResult, TestStatus
from ..core.registry import CATEGORY_PERFORMANCE, register_test
from ..core.runner import TestContext


def _get_sample_path(cfg: FrameworkConfig, kind: str) -> Path:
    """Helper to resolve sample files."""
    if kind == "doc":
        return cfg.dataset_path("documents_genuine") / "genuine_doc.png"
    elif kind == "face_a":
        return cfg.dataset_path("faces_dir") / "person_a.png"
    elif kind == "face_b":
        return cfg.dataset_path("faces_dir") / "person_a_2.png"
    raise ValueError(f"Unknown sample kind: {kind}")


@register_test(
    category=CATEGORY_PERFORMANCE,
    name="pipeline_module_benchmark",
    description="Direct benchmark of available pipeline modules",
    requires_pipeline=True
)
def test_pipeline_modules(cfg: FrameworkConfig, ctx: TestContext) -> TestResult:
    adapters = build_adapters(cfg)
    iterations = cfg.pipeline_iterations
    
    # Fallback to hardcoded samples if datasets not configured correctly yet
    root = cfg.project_root
    doc_path = root / "samples" / "genuine_doc.png"
    face_path = root / "samples" / "faces" / "person_a.png"
    
    metrics = {}
    samples = []
    errors = []
    total_t0 = time.perf_counter()
    
    for name, adapter in adapters.items():
        if not adapter.is_available():
            metrics[f"{name}_status"] = "NOT_AVAILABLE"
            continue
            
        metrics[f"{name}_status"] = "AVAILABLE"
        mod_samples = []
        
        try:
            # Cold start (first run)
            t0 = time.perf_counter()
            if name == "face_match":
                res = adapter.run(face_path, face_path)
            elif name == "liveness":
                 # Need a burst, fake it with a single image for now
                 res = adapter.run([str(face_path)])
            else:
                res = adapter.run(doc_path)
            cold_ms = (time.perf_counter() - t0) * 1000
            
            if res.status == "error":
                errors.append(f"{name} cold start error: {res.error}")
                continue
                
            metrics[f"{name}_cold_ms"] = round(cold_ms, 2)
            mod_samples.append(BenchmarkSample(f"{name}_cold", cold_ms, True))
            
            # Warm runs
            warm_times = []
            for _ in range(iterations):
                t0 = time.perf_counter()
                if name == "face_match":
                    adapter.run(face_path, face_path)
                elif name == "liveness":
                    adapter.run([str(face_path)])
                else:
                    adapter.run(doc_path)
                warm_ms = (time.perf_counter() - t0) * 1000
                warm_times.append(warm_ms)
                mod_samples.append(BenchmarkSample(f"{name}_warm", warm_ms, True))
                
            if warm_times:
                metrics[f"{name}_warm_avg_ms"] = round(sum(warm_times) / len(warm_times), 2)
                
            samples.extend(mod_samples)
            
        except Exception as e:
            errors.append(f"{name} benchmark failed: {e}")
            
    total_ms = (time.perf_counter() - total_t0) * 1000
    status = TestStatus.PASS if not errors else TestStatus.FAIL
    
    return TestResult(
        test_name="pipeline_module_benchmark",
        category=CATEGORY_PERFORMANCE,
        status=status,
        duration_ms=total_ms,
        metrics=metrics,
        samples=samples,
        errors=errors
    )
