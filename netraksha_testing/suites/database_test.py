"""Database test suite.

Simulates DB interactions to measure latency and transaction limits.
"""

from __future__ import annotations

import time

from ..core.config import FrameworkConfig
from ..core.models import TestResult, TestStatus
from ..core.registry import CATEGORY_DATABASE, register_test
from ..core.runner import TestContext

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False


@register_test(
    category=CATEGORY_DATABASE,
    name="db_query_latency",
    description="Test backend database query latency via API",
    requires_api=True
)
def test_database_latency(cfg: FrameworkConfig, ctx: TestContext) -> TestResult:
    if not _HAS_HTTPX:
        return TestResult.not_available("db_query_latency", CATEGORY_DATABASE, "httpx not installed")

    # If we don't have an auth token, we can't test the DB via the API
    if not ctx.api_token:
        return TestResult.skipped("db_query_latency", CATEGORY_DATABASE, "No API auth token available")

    # Use the /api/cases endpoint to trigger DB reads
    url = cfg.api_base_url + cfg.api_endpoints.get("cases", "/api/cases")
    t_start = time.perf_counter()
    
    latencies = []
    errors = []
    headers = {"Authorization": f"Bearer {ctx.api_token}"}
    
    with httpx.Client(timeout=cfg.api_timeout) as client:
        for _ in range(3):  # Run a few times to get average
            t0 = time.perf_counter()
            try:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    latencies.append((time.perf_counter() - t0) * 1000)
                else:
                    errors.append(f"HTTP {resp.status_code}")
            except Exception as e:
                errors.append(str(e))
                
    total_ms = (time.perf_counter() - t_start) * 1000
    metrics = {}
    
    if latencies:
        metrics["db_read_avg_ms"] = sum(latencies) / len(latencies)
        metrics["db_read_min_ms"] = min(latencies)
        metrics["db_read_max_ms"] = max(latencies)
        
    status = TestStatus.PASS if latencies and not errors else TestStatus.FAIL
    
    return TestResult(
        test_name="db_query_latency",
        category=CATEGORY_DATABASE,
        status=status,
        duration_ms=total_ms,
        metrics=metrics,
        errors=list(set(errors))
    )
