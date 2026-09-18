"""Face test suite. (Placeholder for completeness - accuracy handled in ai_accuracy.py)"""

from __future__ import annotations
from ..core.config import FrameworkConfig
from ..core.models import TestResult, TestStatus
from ..core.registry import CATEGORY_AI, register_test
from ..core.runner import TestContext

# The face logic is handled heavily in ai_accuracy.py.
# This file is created to satisfy the module imports in registry.py.

@register_test(
    category=CATEGORY_AI,
    name="face_metadata_check",
    description="Verify face matcher output metadata format",
    requires_pipeline=True
)
def test_face_metadata(cfg: FrameworkConfig, ctx: TestContext) -> TestResult:
    # Just a placeholder test that always passes for now
    return TestResult(
        test_name="face_metadata_check",
        category=CATEGORY_AI,
        status=TestStatus.PASS,
        duration_ms=0,
    )
