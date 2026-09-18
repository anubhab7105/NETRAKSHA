"""Core data models for the Netraksha Testing Framework.

Every test result, metric, and measurement in the framework uses these
dataclasses. No fabricated values — all fields must come from actual
measurements or be explicitly marked with a MetricSource.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class TestStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class MetricSource(str, Enum):
    MEASURED = "MEASURED"          # direct instrumentation
    CALCULATED = "CALCULATED"      # derived from measured values
    ESTIMATED = "ESTIMATED"        # approximated (e.g., from sampling)
    NOT_AVAILABLE = "NOT_AVAILABLE"  # system does not expose this metric
    NOT_TESTED = "NOT_TESTED"      # test category not run


class Severity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ---------------------------------------------------------------------------
# Metric models
# ---------------------------------------------------------------------------

@dataclass
class Metric:
    """A single named, sourced measurement."""
    name: str
    value: Any
    unit: str
    source: MetricSource = MetricSource.MEASURED
    note: Optional[str] = None

    def display(self) -> str:
        if self.value is None or self.value == "NOT_AVAILABLE":
            return f"{self.name}: NOT AVAILABLE [{self.source.value}]"
        unit_str = f" {self.unit}" if self.unit else ""
        return f"{self.name}: {self.value}{unit_str} [{self.source.value}]"


@dataclass
class LatencyStats:
    """Percentile statistics for a set of timing measurements."""
    samples: List[float]          # raw latency values in ms
    count: int = 0
    min_ms: float = 0.0
    max_ms: float = 0.0
    mean_ms: float = 0.0
    median_ms: float = 0.0
    p50_ms: float = 0.0
    p90_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    stddev_ms: float = 0.0
    source: MetricSource = MetricSource.MEASURED

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "min_ms": round(self.min_ms, 2),
            "max_ms": round(self.max_ms, 2),
            "mean_ms": round(self.mean_ms, 2),
            "median_ms": round(self.median_ms, 2),
            "p50_ms": round(self.p50_ms, 2),
            "p90_ms": round(self.p90_ms, 2),
            "p95_ms": round(self.p95_ms, 2),
            "p99_ms": round(self.p99_ms, 2),
            "stddev_ms": round(self.stddev_ms, 2),
            "source": self.source.value,
        }


@dataclass
class ConcurrencyResult:
    """Results for a single concurrency level test."""
    concurrency: int
    total_requests: int
    successful: int
    failed: int
    timed_out: int
    duration_s: float
    throughput_rps: float          # requests per second (CALCULATED)
    latency: LatencyStats
    cpu_percent: Optional[float] = None
    ram_mb: Optional[float] = None
    error_rate: float = 0.0        # CALCULATED


@dataclass
class SecurityFinding:
    """A single security check result."""
    check_name: str
    severity: Severity
    status: str                    # "PASS" | "FAIL" | "INFO" | "SKIPPED"
    description: str
    evidence: Optional[str] = None
    recommendation: Optional[str] = None


@dataclass
class MemoryLeakAnalysis:
    """Linear regression analysis on memory growth."""
    baseline_mb: float
    min_mb: float
    avg_mb: float
    max_mb: float
    slope_mb_per_100req: float     # CALCULATED via linear regression
    r_squared: float
    suspected_leak: bool
    sample_count: int
    note: str
    source: MetricSource = MetricSource.CALCULATED


@dataclass
class BenchmarkSample:
    """A single timed measurement with context."""
    name: str
    duration_ms: float
    success: bool
    extra: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ---------------------------------------------------------------------------
# Test Result
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    """Structured result returned by every test.

    Tests MUST never raise — any failure is captured here.
    status=ERROR means the test framework itself errored (not the system).
    status=FAIL means the system under test failed.
    status=SKIPPED means the test was intentionally not run.
    status=NOT_AVAILABLE means a required component was unavailable.
    """
    test_name: str
    category: str
    status: TestStatus
    duration_ms: float
    metrics: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    samples: List[BenchmarkSample] = field(default_factory=list)
    security_findings: List[SecurityFinding] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def skipped(cls, test_name: str, category: str, reason: str) -> "TestResult":
        return cls(
            test_name=test_name,
            category=category,
            status=TestStatus.SKIPPED,
            duration_ms=0.0,
            warnings=[reason],
        )

    @classmethod
    def not_available(cls, test_name: str, category: str, reason: str) -> "TestResult":
        return cls(
            test_name=test_name,
            category=category,
            status=TestStatus.NOT_AVAILABLE,
            duration_ms=0.0,
            warnings=[f"NOT AVAILABLE: {reason}"],
        )

    @classmethod
    def error(cls, test_name: str, category: str, exc: Exception, duration_ms: float = 0.0) -> "TestResult":
        return cls(
            test_name=test_name,
            category=category,
            status=TestStatus.ERROR,
            duration_ms=duration_ms,
            errors=[f"{type(exc).__name__}: {str(exc)[:500]}"],
        )


# ---------------------------------------------------------------------------
# Hardware snapshot
# ---------------------------------------------------------------------------

@dataclass
class HardwareInfo:
    """Point-in-time hardware information snapshot."""
    cpu_model: str
    cpu_arch: str
    cpu_physical_cores: int
    cpu_logical_cores: int
    cpu_base_freq_mhz: Optional[float]
    cpu_max_freq_mhz: Optional[float]
    cpu_utilization_pct: float
    cpu_temperature_c: Optional[float]
    ram_total_gb: float
    ram_available_gb: float
    ram_used_gb: float
    ram_utilization_pct: float
    swap_total_gb: float
    swap_used_gb: float
    gpu_model: Optional[str]
    gpu_vram_mb: Optional[float]
    gpu_utilization_pct: Optional[float]
    gpu_temperature_c: Optional[float]
    disk_devices: List[Dict[str, Any]]
    disk_total_gb: float
    disk_available_gb: float
    source_notes: Dict[str, MetricSource] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Run metadata (for reproducibility)
# ---------------------------------------------------------------------------

@dataclass
class RunMetadata:
    """Everything needed to reproduce or compare a test run."""
    run_id: str
    timestamp: str
    git_commit: str
    os_name: str
    os_version: str
    python_version: str
    netraksha_pipeline_version: str
    package_versions: Dict[str, str]
    config_snapshot: Dict[str, Any]
    hardware: Optional[HardwareInfo] = None
    dataset_checksums: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# Aggregate run result
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    """Complete results for a single test run."""
    metadata: RunMetadata
    results: List[TestResult] = field(default_factory=list)
    hardware_samples: List[Dict[str, Any]] = field(default_factory=list)
    memory_analysis: Optional[MemoryLeakAnalysis] = None
    bottleneck_findings: List[str] = field(default_factory=list)
    concurrency_results: List[ConcurrencyResult] = field(default_factory=list)

    @property
    def total_tests(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.FAIL)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results
                   if r.status in (TestStatus.SKIPPED, TestStatus.NOT_AVAILABLE))

    @property
    def errors(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.ERROR)

    def to_dict(self) -> dict:
        return {
            "metadata": self.metadata.to_dict(),
            "summary": {
                "total": self.total_tests,
                "passed": self.passed,
                "failed": self.failed,
                "skipped": self.skipped,
                "errors": self.errors,
            },
            "results": [r.to_dict() for r in self.results],
            "bottleneck_findings": self.bottleneck_findings,
            "concurrency_results": [asdict(c) for c in self.concurrency_results],
            "memory_analysis": asdict(self.memory_analysis) if self.memory_analysis else None,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)
