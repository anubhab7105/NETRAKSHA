"""API performance testing suite.

Tests HTTP endpoints using httpx for latency, status codes, and throughput.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from ..core.config import FrameworkConfig
from ..core.models import BenchmarkSample, LatencyStats, MetricSource, TestResult, TestStatus
from ..core.registry import CATEGORY_PERFORMANCE, register_test
from ..core.runner import TestContext

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False


def _calc_latency_stats(samples: List[BenchmarkSample], duration_ms: float) -> Dict[str, Any]:
    if not samples:
        return {}
    
    latencies = sorted(s.duration_ms for s in samples)
    count = len(latencies)
    
    metrics = {
        "count": count,
        "success_rate": sum(1 for s in samples if s.success) / count,
        "throughput_rps": count / (duration_ms / 1000.0) if duration_ms > 0 else 0,
        "min_ms": round(latencies[0], 2),
        "max_ms": round(latencies[-1], 2),
        "mean_ms": round(sum(latencies) / count, 2),
        "median_ms": round(latencies[count // 2], 2),
    }

    # Percentiles
    for p in [50, 90, 95, 99]:
        idx = int(count * (p / 100.0))
        idx = min(idx, count - 1)
        metrics[f"p{p}_ms"] = round(latencies[idx], 2)
        
    return metrics


@register_test(
    category=CATEGORY_PERFORMANCE,
    name="api_health_benchmark",
    description="Benchmark /api/health endpoint",
    requires_api=True
)
def test_api_health(cfg: FrameworkConfig, ctx: TestContext) -> TestResult:
    if not _HAS_HTTPX:
        return TestResult.not_available("api_health_benchmark", CATEGORY_PERFORMANCE, "httpx not installed")

    url = cfg.api_base_url + cfg.api_endpoints.get("health", "/api/health")
    iterations = cfg.api_iterations
    samples = []
    errors = []

    t_start = time.perf_counter()
    with httpx.Client(timeout=cfg.api_timeout) as client:
        for _ in range(iterations):
            t0 = time.perf_counter()
            success = False
            try:
                resp = client.get(url)
                success = resp.status_code == 200
                if not success:
                    errors.append(f"HTTP {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                errors.append(str(e))
            
            elapsed = (time.perf_counter() - t0) * 1000
            samples.append(BenchmarkSample(name="health", duration_ms=elapsed, success=success))
    
    total_ms = (time.perf_counter() - t_start) * 1000
    metrics = _calc_latency_stats(samples, total_ms)
    
    status = TestStatus.PASS if metrics.get("success_rate", 0) > 0.9 else TestStatus.FAIL

    return TestResult(
        test_name="api_health_benchmark",
        category=CATEGORY_PERFORMANCE,
        status=status,
        duration_ms=total_ms,
        metrics=metrics,
        samples=samples,
        errors=list(set(errors))
    )


@register_test(
    category=CATEGORY_PERFORMANCE,
    name="api_auth_benchmark",
    description="Benchmark /api/auth/login endpoint",
    requires_api=True
)
def test_api_auth(cfg: FrameworkConfig, ctx: TestContext) -> TestResult:
    if not _HAS_HTTPX:
        return TestResult.not_available("api_auth_benchmark", CATEGORY_PERFORMANCE, "httpx not installed")

    password = cfg.api_password
    if not password:
         return TestResult.skipped("api_auth_benchmark", CATEGORY_PERFORMANCE, "No test password configured")

    url = cfg.api_base_url + cfg.api_endpoints.get("login", "/api/auth/login")
    iterations = min(cfg.api_iterations, 5) # Keep auth tests lower to avoid rate limits
    samples = []
    errors = []

    t_start = time.perf_counter()
    with httpx.Client(timeout=cfg.api_timeout) as client:
        for _ in range(iterations):
            t0 = time.perf_counter()
            success = False
            try:
                resp = client.post(url, json={"username": cfg.api_username, "password": password})
                success = resp.status_code == 200
                if not success:
                    errors.append(f"HTTP {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                errors.append(str(e))
            
            elapsed = (time.perf_counter() - t0) * 1000
            samples.append(BenchmarkSample(name="auth_login", duration_ms=elapsed, success=success))
            time.sleep(0.1) # Small delay to avoid brute-force triggers
            
    total_ms = (time.perf_counter() - t_start) * 1000
    metrics = _calc_latency_stats(samples, total_ms)
    
    status = TestStatus.PASS if metrics.get("success_rate", 0) > 0.5 else TestStatus.FAIL

    return TestResult(
        test_name="api_auth_benchmark",
        category=CATEGORY_PERFORMANCE,
        status=status,
        duration_ms=total_ms,
        metrics=metrics,
        samples=samples,
        errors=list(set(errors))
    )
