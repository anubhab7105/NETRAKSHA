"""AI accuracy evaluation suite.

Evaluates AI models against labeled datasets.
"""

from __future__ import annotations

import csv
import time
from pathlib import Path

from ..core.adapters import build_adapters
from ..core.config import FrameworkConfig
from ..core.models import TestResult, TestStatus
from ..core.registry import CATEGORY_AI, register_test
from ..core.runner import TestContext


@register_test(
    category=CATEGORY_AI,
    name="face_verification_accuracy",
    description="Evaluate face verification accuracy (FAR/FRR)",
    requires_pipeline=True
)
def test_face_accuracy(cfg: FrameworkConfig, ctx: TestContext) -> TestResult:
    adapters = build_adapters(cfg)
    face_adapter = adapters.get("face_match")
    
    if not face_adapter or not face_adapter.is_available():
        return TestResult.not_available("face_verification_accuracy", CATEGORY_AI, "Face match module unavailable")

    root = cfg.project_root
    face_dir = root / "samples" / "faces"
    
    # We'll use the existing samples directly for now since CSVs might not exist
    genuine_pair = (face_dir / "person_a.png", face_dir / "person_a_2.png")
    impostor_pair = (face_dir / "person_a.png", face_dir / "person_b.png")
    
    if not genuine_pair[0].exists() or not genuine_pair[1].exists():
         return TestResult.skipped("face_verification_accuracy", CATEGORY_AI, "Face samples missing")

    t_start = time.perf_counter()
    metrics = {}
    errors = []
    
    try:
        # Genuine pair
        res_gen = face_adapter.run(genuine_pair[0], genuine_pair[1])
        if res_gen.success:
            metrics["genuine_score"] = res_gen.score
            metrics["genuine_match"] = bool(res_gen.raw_output.get("match"))
        else:
            errors.append(f"Genuine match failed: {res_gen.error}")
            
        # Impostor pair
        res_imp = face_adapter.run(impostor_pair[0], impostor_pair[1])
        if res_imp.success:
            metrics["impostor_score"] = res_imp.score
            metrics["impostor_match"] = bool(res_imp.raw_output.get("match"))
        else:
            errors.append(f"Impostor match failed: {res_imp.error}")
            
        # Basic FRR/FAR calculation (on a sample size of 2, it's trivial)
        threshold = cfg.thresholds.get("face_match", 0.55)
        metrics["threshold_used"] = threshold
        
        if "genuine_score" in metrics and "impostor_score" in metrics:
             metrics["frr"] = 0.0 if metrics["genuine_score"] >= threshold else 1.0
             metrics["far"] = 1.0 if metrics["impostor_score"] >= threshold else 0.0
             
    except Exception as e:
        errors.append(str(e))
        
    total_ms = (time.perf_counter() - t_start) * 1000
    
    return TestResult(
        test_name="face_verification_accuracy",
        category=CATEGORY_AI,
        status=TestStatus.PASS if not errors else TestStatus.FAIL,
        duration_ms=total_ms,
        metrics=metrics,
        errors=errors,
        warnings=["Sample size is too small for statistical significance (N=2)"]
    )
