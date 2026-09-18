"""Stability test suite.

Runs long-running soak tests to detect memory leaks and resource degradation.
"""

from __future__ import annotations

import time
from typing import List

from ..core.config import FrameworkConfig
from ..core.models import BenchmarkSample, LatencyStats, TestResult, TestStatus
from ..core.registry import CATEGORY_STABILITY, register_test
from ..core.runner import TestContext

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False


@register_test(
    category=CATEGORY_STABILITY,
    name="api_soak_test",
    description="Run repeated requests to monitor for memory growth",
    requires_api=True
)
def test_stability(cfg: FrameworkConfig, ctx: TestContext) -> TestResult:
    if not _HAS_HTTPX:
        return TestResult.not_available("api_soak_test", CATEGORY_STABILITY, "httpx not installed")

    url = cfg.api_base_url + cfg.api_endpoints.get("health", "/api/health")
    iterations = cfg.stability_iterations
    
    t_start = time.perf_counter()
    samples: List[BenchmarkSample] = []
    errors = []
    
    with httpx.Client(timeout=cfg.api_timeout) as client:
        for i in range(iterations):
            t0 = time.perf_counter()
            success = False
            try:
                resp = client.get(url)
                success = resp.status_code == 200
                if not success:
                    errors.append(f"Iteration {i}: HTTP {resp.status_code}")
            except Exception as e:
                errors.append(f"Iteration {i}: {e}")
                
            elapsed = (time.perf_counter() - t0) * 1000
            samples.append(BenchmarkSample(name=f"soak_{i}", duration_ms=elapsed, success=success))
            
            # Tiny sleep to avoid completely overwhelming the server while still soaking
            time.sleep(0.05)
            
    total_ms = (time.perf_counter() - t_start) * 1000
    
    # Simple success check - memory leak analysis happens globally in runner.py
    # over the hardware_samples collected during this period
    success_rate = sum(1 for s in samples if s.success) / len(samples) if samples else 0
    status = TestStatus.PASS if success_rate > 0.95 else TestStatus.FAIL
    
    return TestResult(
        test_name="api_soak_test",
        category=CATEGORY_STABILITY,
        status=status,
        duration_ms=total_ms,
        metrics={"success_rate": success_rate, "iterations": iterations},
        samples=samples,
        errors=errors[:10] # Cap error list
    )
