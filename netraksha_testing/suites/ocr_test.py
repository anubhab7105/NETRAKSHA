"""OCR testing suite.

Detailed evaluation of OCR extraction accuracy and latency.
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
    name="ocr_extraction_accuracy",
    description="Evaluate OCR accuracy and Tesseract performance",
    requires_pipeline=True
)
def test_ocr_accuracy(cfg: FrameworkConfig, ctx: TestContext) -> TestResult:
    adapters = build_adapters(cfg)
    ocr_adapter = adapters.get("ocr")
    
    if not ocr_adapter or not ocr_adapter.is_available():
        return TestResult.not_available("ocr_extraction_accuracy", CATEGORY_AI, "OCR module unavailable")

    root = cfg.project_root
    doc_path = root / "samples" / "genuine_doc.png"
    
    if not doc_path.exists():
         return TestResult.skipped("ocr_extraction_accuracy", CATEGORY_AI, "Sample document missing")

    t_start = time.perf_counter()
    metrics = {}
    errors = []
    
    try:
        res = ocr_adapter.run(doc_path)
        metrics["success"] = res.success
        metrics["latency_ms"] = res.duration_ms
        
        if res.success:
            # Check for basic fields that should be extracted
            raw = res.raw_output
            extracted_fields = sum(1 for v in raw.values() if v)
            metrics["fields_extracted"] = extracted_fields
            metrics["score"] = res.score
        else:
            errors.append(f"OCR failed: {res.error}")
            
    except Exception as e:
        errors.append(str(e))
        
    total_ms = (time.perf_counter() - t_start) * 1000
    status = TestStatus.PASS if not errors and metrics.get("success") else TestStatus.FAIL
    
    return TestResult(
        test_name="ocr_extraction_accuracy",
        category=CATEGORY_AI,
        status=status,
        duration_ms=total_ms,
        metrics=metrics,
        errors=errors
    )
