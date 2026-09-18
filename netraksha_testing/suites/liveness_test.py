"""Liveness test suite.

Evaluates MediaPipe blink/EAR tracking.
"""

from __future__ import annotations

import time

from ..core.adapters import build_adapters
from ..core.config import FrameworkConfig
from ..core.models import TestResult, TestStatus
from ..core.registry import CATEGORY_AI, register_test
from ..core.runner import TestContext


@register_test(
    category=CATEGORY_AI,
    name="liveness_detection_accuracy",
    description="Evaluate liveness detection on frame bursts",
    requires_pipeline=True
)
def test_liveness_accuracy(cfg: FrameworkConfig, ctx: TestContext) -> TestResult:
    adapters = build_adapters(cfg)
    liveness_adapter = adapters.get("liveness")
    
    if not liveness_adapter or not liveness_adapter.is_available():
        return TestResult.not_available("liveness_detection_accuracy", CATEGORY_AI, "Liveness module unavailable")

    root = cfg.project_root
    face_dir = root / "samples" / "faces"
    
    # Simulate a burst with duplicates if we don't have real bursts
    # (In a real setup we'd load an MP4 or sequence of frames)
    sample_frame = face_dir / "person_a.png"
    
    if not sample_frame.exists():
         return TestResult.skipped("liveness_detection_accuracy", CATEGORY_AI, "Liveness sample missing")

    t_start = time.perf_counter()
    metrics = {}
    errors = []
    
    # 5 frames simulated burst
    frames = [str(sample_frame)] * 5
    
    try:
        res = liveness_adapter.run(frames, challenge_type="static")
        metrics["latency_ms"] = res.duration_ms
        if res.success:
            metrics["score"] = res.score
        else:
            errors.append(f"Liveness check failed: {res.error}")
             
    except Exception as e:
        errors.append(str(e))
        
    total_ms = (time.perf_counter() - t_start) * 1000
    status = TestStatus.PASS if not errors else TestStatus.FAIL
    
    return TestResult(
        test_name="liveness_detection_accuracy",
        category=CATEGORY_AI,
        status=status,
        duration_ms=total_ms,
        metrics=metrics,
        errors=errors
    )
