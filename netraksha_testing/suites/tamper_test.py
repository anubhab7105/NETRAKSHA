"""Tamper testing suite.

Detailed evaluation of ELA and clone detection.
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
    name="tamper_detection_accuracy",
    description="Evaluate ELA and copy-move tamper detection",
    requires_pipeline=True
)
def test_tamper_accuracy(cfg: FrameworkConfig, ctx: TestContext) -> TestResult:
    adapters = build_adapters(cfg)
    tamper_adapter = adapters.get("tamper")
    
    if not tamper_adapter or not tamper_adapter.is_available():
        return TestResult.not_available("tamper_detection_accuracy", CATEGORY_AI, "Tamper module unavailable")

    root = cfg.project_root
    genuine_path = root / "samples" / "genuine_doc.png"
    tampered_path = root / "samples" / "tampered_doc.png"
    
    if not genuine_path.exists() or not tampered_path.exists():
         return TestResult.skipped("tamper_detection_accuracy", CATEGORY_AI, "Tamper sample documents missing")

    t_start = time.perf_counter()
    metrics = {}
    errors = []
    
    try:
        # Genuine doc
        res_gen = tamper_adapter.run(genuine_path)
        metrics["genuine_latency_ms"] = res_gen.duration_ms
        if res_gen.success:
            metrics["genuine_score"] = res_gen.score
            metrics["genuine_flagged"] = bool(res_gen.raw_output.get("is_tampered"))
        else:
            errors.append(f"Genuine check failed: {res_gen.error}")
            
        # Tampered doc
        res_tamp = tamper_adapter.run(tampered_path)
        metrics["tampered_latency_ms"] = res_tamp.duration_ms
        if res_tamp.success:
            metrics["tampered_score"] = res_tamp.score
            metrics["tampered_flagged"] = bool(res_tamp.raw_output.get("is_tampered"))
        else:
            errors.append(f"Tampered check failed: {res_tamp.error}")
            
        # Check if the contract is met (<1.5s as per requirements)
        if res_gen.duration_ms > 1500 or res_tamp.duration_ms > 1500:
             metrics["sla_breached"] = True
             errors.append("Tamper detection exceeded 1.5s SLA")
             
    except Exception as e:
        errors.append(str(e))
        
    total_ms = (time.perf_counter() - t_start) * 1000
    status = TestStatus.PASS if not errors else TestStatus.FAIL
    
    return TestResult(
        test_name="tamper_detection_accuracy",
        category=CATEGORY_AI,
        status=status,
        duration_ms=total_ms,
        metrics=metrics,
        errors=errors
    )
