"""Test registry — decorator-based auto-registration of all test functions.

Every test suite registers its tests with @register_test().
The runner discovers them by category and executes them safely.
"""

from __future__ import annotations

import functools
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

from .models import TestResult, TestStatus

# ---------------------------------------------------------------------------
# Registry storage
# ---------------------------------------------------------------------------

_REGISTRY: Dict[str, "TestEntry"] = {}  # name → entry


class TestEntry:
    """Metadata for a registered test."""

    def __init__(
        self,
        name: str,
        category: str,
        fn: Callable,
        description: str = "",
        requires_api: bool = False,
        requires_pipeline: bool = False,
        requires_db: bool = False,
        requires_dataset: bool = False,
        timeout_s: Optional[float] = None,
    ):
        self.name = name
        self.category = category
        self.fn = fn
        self.description = description
        self.requires_api = requires_api
        self.requires_pipeline = requires_pipeline
        self.requires_db = requires_db
        self.requires_dataset = requires_dataset
        self.timeout_s = timeout_s

    def __repr__(self) -> str:
        return f"TestEntry({self.name!r}, category={self.category!r})"


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def register_test(
    category: str,
    name: Optional[str] = None,
    description: str = "",
    requires_api: bool = False,
    requires_pipeline: bool = False,
    requires_db: bool = False,
    requires_dataset: bool = False,
    timeout_s: Optional[float] = None,
) -> Callable:
    """Register a test function with the global registry.

    Usage::

        @register_test(category="api", name="health_check",
                       requires_api=True, description="GET /api/health")
        def test_health(cfg, ctx) -> TestResult:
            ...

    The decorated function signature must be:
        fn(cfg: FrameworkConfig, ctx: TestContext) -> TestResult

    It will be wrapped in try/except so it can never crash the runner.
    """
    def decorator(fn: Callable) -> Callable:
        test_name = name or fn.__name__

        @functools.wraps(fn)
        def safe_wrapper(cfg: Any, ctx: Any) -> TestResult:
            start = time.perf_counter()
            try:
                result = fn(cfg, ctx)
                # Ensure we always get a TestResult back
                if not isinstance(result, TestResult):
                    elapsed = (time.perf_counter() - start) * 1000
                    return TestResult(
                        test_name=test_name,
                        category=category,
                        status=TestStatus.ERROR,
                        duration_ms=elapsed,
                        errors=[f"Test function did not return TestResult, got {type(result).__name__}"],
                    )
                return result
            except Exception as exc:
                elapsed = (time.perf_counter() - start) * 1000
                tb = traceback.format_exc()
                return TestResult(
                    test_name=test_name,
                    category=category,
                    status=TestStatus.ERROR,
                    duration_ms=elapsed,
                    errors=[f"{type(exc).__name__}: {str(exc)[:300]}", tb[-500:]],
                )

        entry = TestEntry(
            name=test_name,
            category=category,
            fn=safe_wrapper,
            description=description,
            requires_api=requires_api,
            requires_pipeline=requires_pipeline,
            requires_db=requires_db,
            requires_dataset=requires_dataset,
            timeout_s=timeout_s,
        )
        _REGISTRY[test_name] = entry
        return safe_wrapper

    return decorator


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def auto_discover() -> None:
    """Import all suite modules to trigger @register_test decorators."""
    import importlib
    suite_modules = [
        "netraksha_testing.suites.api_performance",
        "netraksha_testing.suites.pipeline_benchmark",
        "netraksha_testing.suites.ai_accuracy",
        "netraksha_testing.suites.ocr_test",
        "netraksha_testing.suites.face_test",
        "netraksha_testing.suites.tamper_test",
        "netraksha_testing.suites.liveness_test",
        "netraksha_testing.suites.database_test",
        "netraksha_testing.suites.network_test",
        "netraksha_testing.suites.security_checks",
        "netraksha_testing.suites.concurrency_test",
        "netraksha_testing.suites.stability_test",
        "netraksha_testing.suites.failure_recovery",
    ]
    for mod_name in suite_modules:
        try:
            importlib.import_module(mod_name)
        except ImportError as e:
            # Log but don't crash — optional dependencies may be missing
            print(f"[registry] Could not import {mod_name}: {e}")
        except Exception as e:
            print(f"[registry] Error importing {mod_name}: {e}")


def get_tests(categories: Optional[List[str]] = None) -> List[TestEntry]:
    """Return registered tests, optionally filtered by category."""
    entries = list(_REGISTRY.values())
    if categories:
        entries = [e for e in entries if e.category in categories]
    return entries


def get_all_categories() -> List[str]:
    """Return all registered category names."""
    return sorted(set(e.category for e in _REGISTRY.values()))


# Category constants (used in CLI flags)
CATEGORY_SYSTEM = "system"
CATEGORY_PERFORMANCE = "performance"
CATEGORY_AI = "ai"
CATEGORY_SECURITY = "security"
CATEGORY_LOAD = "load"
CATEGORY_STABILITY = "stability"
CATEGORY_DATABASE = "database"
CATEGORY_NETWORK = "network"
CATEGORY_FAILURE = "failure"

CATEGORY_GROUPS = {
    "system": [CATEGORY_SYSTEM],
    "performance": [CATEGORY_PERFORMANCE],
    "ai": [CATEGORY_AI],
    "security": [CATEGORY_SECURITY],
    "load": [CATEGORY_LOAD],
    "stability": [CATEGORY_STABILITY],
    "database": [CATEGORY_DATABASE],
    "network": [CATEGORY_NETWORK],
    "failure": [CATEGORY_FAILURE],
    "all": None,  # None = no filter = run everything
}
