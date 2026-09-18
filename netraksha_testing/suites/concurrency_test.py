"""Concurrency and load testing suite.

Ramps up concurrent requests to identify performance degradation.
"""

from __future__ import annotations

import asyncio
import time
from typing import List

from ..core.config import FrameworkConfig
from ..core.models import ConcurrencyResult, LatencyStats, MetricSource, TestResult, TestStatus
from ..core.registry import CATEGORY_LOAD, register_test
from ..core.runner import TestContext

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False


async def _make_request(client: httpx.AsyncClient, url: str) -> float:
    t0 = time.perf_counter()
    try:
        resp = await client.get(url)
        if resp.status_code == 200:
             return (time.perf_counter() - t0) * 1000
    except Exception:
        pass
    return -1.0


async def _run_concurrency_level(url: str, concurrency: int, num_requests: int, timeout: int) -> ConcurrencyResult:
    t_start = time.perf_counter()
    latencies: List[float] = []
    failed = 0
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        # Create a semaphore to limit concurrency
        sem = asyncio.Semaphore(concurrency)
        
        async def bounded_request():
            async with sem:
                return await _make_request(client, url)
                
        tasks = [bounded_request() for _ in range(num_requests)]
        results = await asyncio.gather(*tasks)
        
        for r in results:
            if r > 0:
                latencies.append(r)
            else:
                failed += 1
                
    duration_s = time.perf_counter() - t_start
    success = len(latencies)
    
    lat_stats = LatencyStats(samples=latencies)
    if latencies:
        latencies.sort()
        count = len(latencies)
        lat_stats.count = count
        lat_stats.min_ms = latencies[0]
        lat_stats.max_ms = latencies[-1]
        lat_stats.mean_ms = sum(latencies) / count
        lat_stats.median_ms = latencies[count // 2]
        
        p95_idx = min(int(count * 0.95), count - 1)
        lat_stats.p95_ms = latencies[p95_idx]
    
    return ConcurrencyResult(
        concurrency=concurrency,
        total_requests=num_requests,
        successful=success,
        failed=failed,
        timed_out=0, # Simplified for now
        duration_s=duration_s,
        throughput_rps=success / duration_s if duration_s > 0 else 0,
        latency=lat_stats,
        error_rate=(failed / num_requests) if num_requests > 0 else 0
    )


@register_test(
    category=CATEGORY_LOAD,
    name="api_load_ramp",
    description="Ramp up concurrent requests to find degradation point",
    requires_api=True
)
def test_concurrency(cfg: FrameworkConfig, ctx: TestContext) -> TestResult:
    if not _HAS_HTTPX:
        return TestResult.not_available("api_load_ramp", CATEGORY_LOAD, "httpx not installed")

    url = cfg.api_base_url + cfg.concurrency_target_endpoint if hasattr(cfg, 'concurrency_target_endpoint') else cfg.api_base_url + "/api/health"
    levels = cfg.concurrency_levels
    reqs_per_level = cfg.concurrency_requests_per_level
    
    t_start = time.perf_counter()
    results = []
    
    try:
        # Need to run async code from sync context
        loop = asyncio.get_event_loop()
        if loop.is_closed():
             loop = asyncio.new_event_loop()
             asyncio.set_event_loop(loop)
             
        for level in levels:
             # Run the async level test
             res = loop.run_until_complete(
                 _run_concurrency_level(url, level, reqs_per_level, cfg.api_timeout)
             )
             results.append(res)
             time.sleep(1) # Cool down between levels
             
    except Exception as e:
        return TestResult.error("api_load_ramp", CATEGORY_LOAD, e, (time.perf_counter() - t_start) * 1000)
        
    # Store results in the runner context so the HTML report can grab them
    # This is a bit of a hack, a better way would be to extend TestResult
    ctx.set("concurrency_results", results)
    
    return TestResult(
        test_name="api_load_ramp",
        category=CATEGORY_LOAD,
        status=TestStatus.PASS,
        duration_ms=(time.perf_counter() - t_start) * 1000,
        metrics={"max_concurrency_tested": max(levels), "levels_tested": len(levels)}
    )
