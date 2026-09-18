"""Network testing suite.

Tests network reliability, payload size limits, and external service latency.
"""

from __future__ import annotations

import time

from ..core.config import FrameworkConfig
from ..core.models import TestResult, TestStatus
from ..core.registry import CATEGORY_NETWORK, register_test
from ..core.runner import TestContext

try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False


@register_test(
    category=CATEGORY_NETWORK,
    name="network_payload_handling",
    description="Test handling of large multipart payloads",
    requires_api=True
)
def test_network_payload(cfg: FrameworkConfig, ctx: TestContext) -> TestResult:
    if not _HAS_HTTPX:
        return TestResult.not_available("network_payload_handling", CATEGORY_NETWORK, "httpx not installed")

    # If we don't have an auth token, skip
    if not ctx.api_token:
        return TestResult.skipped("network_payload_handling", CATEGORY_NETWORK, "No API auth token available")

    # Test the /api/screen endpoint with a dummy image payload
    # Note: We expect this to fail gracefully if the image isn't valid, but it should handle the *upload* part correctly.
    url = cfg.api_base_url + cfg.api_endpoints.get("screen", "/api/screen")
    t_start = time.perf_counter()
    errors = []
    metrics = {}
    
    headers = {"Authorization": f"Bearer {ctx.api_token}"}
    
    # Create a dummy 1MB payload to simulate a medium-sized image
    dummy_data = b"0" * (1024 * 1024)
    files = {'document_image': ('dummy.png', dummy_data, 'image/png')}
    
    # In Netraksha, idempotency key is required
    import uuid
    data = {'idempotency_key': str(uuid.uuid4())}
    
    try:
        t0 = time.perf_counter()
        with httpx.Client(timeout=cfg.api_timeout) as client:
            resp = client.post(url, headers=headers, data=data, files=files)
            upload_time = (time.perf_counter() - t0) * 1000
            metrics["upload_time_ms"] = round(upload_time, 2)
            metrics["status_code"] = resp.status_code
            
            # The pipeline will likely fail because dummy.png isn't a real image,
            # but the server shouldn't crash (e.g. 500 error). It should return 422 or process it and say inconclusive.
            if resp.status_code >= 500:
                errors.append(f"Server crashed (HTTP {resp.status_code}) on 1MB payload upload")
                
    except Exception as e:
        errors.append(f"Upload failed: {e}")
        
    total_ms = (time.perf_counter() - t_start) * 1000
    status = TestStatus.PASS if not errors else TestStatus.FAIL
    
    return TestResult(
        test_name="network_payload_handling",
        category=CATEGORY_NETWORK,
        status=status,
        duration_ms=total_ms,
        metrics=metrics,
        errors=errors
    )
