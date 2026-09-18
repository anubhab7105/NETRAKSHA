"""Test runner — orchestrates the full testing pipeline.

Coordinates: environment detection → resource monitoring → test execution
→ analysis → visualization → report generation.
"""

from __future__ import annotations

import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import FrameworkConfig
from .models import RunResult, RunMetadata, TestResult, TestStatus
from .registry import TestEntry


# ---------------------------------------------------------------------------
# Test context (passed to every test function)
# ---------------------------------------------------------------------------

@dataclass
class TestContext:
    """Context object passed to every test function."""
    cfg: FrameworkConfig
    run_id: str
    output_dir: Path
    api_token: Optional[str] = None       # JWT obtained at start of run
    netraksha_pid: Optional[int] = None   # PID of uvicorn process
    available_modules: Dict[str, bool] = field(default_factory=dict)
    _extras: Dict[str, Any] = field(default_factory=dict)

    def set(self, key: str, value: Any) -> None:
        self._extras[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._extras.get(key, default)


# ---------------------------------------------------------------------------
# Progress display
# ---------------------------------------------------------------------------

class ProgressDisplay:
    """Clean terminal progress indicator."""

    ICON_PASS = "[PASS]"
    ICON_FAIL = "[FAIL]"
    ICON_SKIP = "[SKIP]"
    ICON_RUN  = "[RUN ]"
    ICON_ERR  = "[ERR ]"

    # ANSI colors
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    GRAY   = "\033[90m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"

    def __init__(self, quiet: bool = False, no_color: bool = False):
        self.quiet = quiet
        self.no_color = no_color or not sys.stdout.isatty()

    def _c(self, color: str, text: str) -> str:
        if self.no_color:
            return text
        return f"{color}{text}{self.RESET}"

    def header(self, title: str) -> None:
        if self.quiet:
            return
        width = 60
        print()
        print(self._c(self.BOLD, "=" * width))
        print(self._c(self.BOLD, f"  {title}"))
        print(self._c(self.BOLD, "=" * width))
        print()

    def section(self, title: str) -> None:
        if self.quiet:
            return
        print(self._c(self.CYAN, f"\n-- {title} --"))

    def test_start(self, name: str) -> None:
        if self.quiet:
            return
        print(f"  {self._c(self.GRAY, self.ICON_RUN)} {name} ...", end="", flush=True)

    def test_done(self, result: TestResult) -> None:
        if self.quiet:
            return
        status = result.status
        if status == TestStatus.PASS:
            icon = self._c(self.GREEN, f"[{self.ICON_PASS}]")
        elif status == TestStatus.FAIL:
            icon = self._c(self.RED, f"[{self.ICON_FAIL}]")
        elif status in (TestStatus.SKIPPED, TestStatus.NOT_AVAILABLE):
            icon = self._c(self.YELLOW, f"[{self.ICON_SKIP}]")
        else:
            icon = self._c(self.RED, f"[{self.ICON_ERR}]")

        ms_str = f"{result.duration_ms:.1f}ms"
        print(f"\r  {icon} {result.test_name:<45} {self._c(self.GRAY, ms_str)}")

        if result.errors and not self.quiet:
            for e in result.errors[:2]:
                print(self._c(self.RED, f"       {e[:120]}"))
        if result.warnings and not self.quiet:
            for w in result.warnings[:2]:
                print(self._c(self.YELLOW, f"       {w[:120]}"))

    def summary(self, run_result: RunResult, total_duration_s: float) -> None:
        if self.quiet:
            return
        print()
        print(self._c(self.BOLD, "-" * 60))
        print(self._c(self.BOLD, "  FINAL SUMMARY"))
        print(self._c(self.BOLD, "-" * 60))
        print(f"  Tests Executed : {run_result.total_tests}")
        print(f"  {self._c(self.GREEN, 'Passed')}         : {run_result.passed}")
        print(f"  {self._c(self.RED, 'Failed')}         : {run_result.failed}")
        print(f"  {self._c(self.YELLOW, 'Skipped/N/A')}    : {run_result.skipped}")
        print(f"  {self._c(self.RED, 'Errors')}         : {run_result.errors}")
        print(f"  Total Duration : {total_duration_s:.1f}s")
        print()

    def info(self, msg: str) -> None:
        if self.quiet:
            return
        print(f"  {self._c(self.GRAY, '*')} {msg}")

    def warn(self, msg: str) -> None:
        print(f"  {self._c(self.YELLOW, '!')} {msg}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class TestRunner:
    """Main orchestrator for the Netraksha testing framework."""

    def __init__(
        self,
        cfg: FrameworkConfig,
        categories: Optional[List[str]] = None,
        verbose: bool = False,
        quiet: bool = False,
    ):
        self.cfg = cfg
        self.categories = categories  # None = run all
        self.verbose = verbose
        self.quiet = quiet
        self.display = ProgressDisplay(quiet=quiet)

    def run(self) -> RunResult:
        """Execute the full test run and return aggregate results."""
        from .registry import auto_discover, get_tests, CATEGORY_GROUPS
        from ..collectors.environment import collect_environment
        from ..collectors.hardware import collect_hardware
        from ..collectors.resource_monitor import ResourceMonitor
        from ..utils.logger import get_logger

        log = get_logger(__name__)
        run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        start_wall = time.perf_counter()

        self.display.header(f"Netraksha Test Suite  [{run_id}]")
        self.display.info(f"API: {self.cfg.api_base_url}")
        self.display.info(f"Output: {self.cfg.output_dir}")

        # Ensure output directories exist
        self._ensure_output_dirs()

        # ── Environment detection ───────────────────────────────────────────
        self.display.section("Environment Detection")
        env_info = collect_environment(self.cfg)
        hw_info = collect_hardware()

        meta = RunMetadata(
            run_id=run_id,
            timestamp=datetime.utcnow().isoformat(),
            git_commit=env_info.get("git_commit", "unknown"),
            os_name=env_info.get("os_name", "unknown"),
            os_version=env_info.get("os_version", "unknown"),
            python_version=env_info.get("python_version", "unknown"),
            netraksha_pipeline_version=env_info.get("netraksha_pipeline_version", "unknown"),
            package_versions=env_info.get("package_versions", {}),
            config_snapshot=self.cfg.to_dict(),
            hardware=hw_info,
        )
        self.display.info(f"OS: {meta.os_name} {meta.os_version}")
        self.display.info(f"Python: {meta.python_version}")
        self.display.info(f"Pipeline: {meta.netraksha_pipeline_version}")
        if hw_info:
            self.display.info(f"CPU: {hw_info.cpu_model} ({hw_info.cpu_physical_cores}c/{hw_info.cpu_logical_cores}t)")
            self.display.info(f"RAM: {hw_info.ram_total_gb:.1f} GB total")
            gpu_str = hw_info.gpu_model or "NOT AVAILABLE"
            self.display.info(f"GPU: {gpu_str}")

        run_result = RunResult(metadata=meta)

        # ── Discover tests ──────────────────────────────────────────────────
        auto_discover()

        # Resolve categories to run
        if self.categories is None:
            # Run all
            tests = get_tests()
        else:
            # Expand category group aliases
            cat_set = set()
            for cat in self.categories:
                resolved = CATEGORY_GROUPS.get(cat, [cat])
                if resolved is None:
                    tests = get_tests()
                    cat_set = None
                    break
                cat_set.update(resolved)
            if cat_set is not None:
                tests = get_tests(categories=list(cat_set))
            # tests already set if cat_set is None (all)

        # ── Setup API auth token ────────────────────────────────────────────
        ctx = TestContext(
            cfg=self.cfg,
            run_id=run_id,
            output_dir=self.cfg.output_dir,
        )
        self._try_api_auth(ctx)

        # ── Detect available pipeline modules ───────────────────────────────
        self._detect_pipeline_modules(ctx)

        # ── Start resource monitor ──────────────────────────────────────────
        resource_samples: List[Dict] = []
        monitor = ResourceMonitor(
            interval_s=self.cfg.sampling_interval,
            output=resource_samples,
        )
        monitor.start()

        # ── Execute tests ───────────────────────────────────────────────────
        for entry in tests:
            self.display.section(entry.category.upper()) if self._new_category(entry, tests) else None
            self.display.test_start(entry.name)

            # Check preconditions
            skip_reason = self._check_preconditions(entry, ctx)
            if skip_reason:
                result = TestResult.skipped(entry.name, entry.category, skip_reason)
            else:
                result = entry.fn(self.cfg, ctx)

            run_result.results.append(result)
            self.display.test_done(result)

        # ── Stop resource monitor ───────────────────────────────────────────
        monitor.stop()
        run_result.hardware_samples = resource_samples

        # ── Analysis ────────────────────────────────────────────────────────
        self.display.section("Analysis")
        self._run_analysis(run_result)

        # ── Visualization ───────────────────────────────────────────────────
        self.display.section("Generating Charts")
        self._run_visualization(run_result)

        # ── Report generation ───────────────────────────────────────────────
        self.display.section("Generating Report")
        report_paths = self._run_reporting(run_result)
        for path in report_paths:
            self.display.info(f"Report: {path}")

        # ── Save raw JSON ───────────────────────────────────────────────────
        raw_path = self.cfg.output_dir / "raw" / f"{run_id}.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(run_result.to_json(), encoding="utf-8")
        self.display.info(f"Raw data: {raw_path}")

        total_duration = time.perf_counter() - start_wall
        self.display.summary(run_result, total_duration)
        return run_result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_output_dirs(self) -> None:
        for sub in ["raw", "charts", "diagrams", "reports", "metrics"]:
            (self.cfg.output_dir / sub).mkdir(parents=True, exist_ok=True)

    def _try_api_auth(self, ctx: TestContext) -> None:
        """Attempt to obtain a JWT token for API tests."""
        password = self.cfg.api_password
        if not password:
            self.display.warn("TEST_PASSWORD env var not set — API auth tests may be skipped")
            return
        try:
            import httpx
            url = self.cfg.api_base_url + self.cfg.api_endpoints.get("login", "/api/auth/login")
            resp = httpx.post(
                url,
                json={"username": self.cfg.api_username, "password": password},
                timeout=self.cfg.api_timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                ctx.api_token = data.get("access_token") or data.get("token")
                if ctx.api_token:
                    self.display.info(f"API auth: OK (user={self.cfg.api_username})")
                else:
                    self.display.warn("Login succeeded but no token in response")
            else:
                self.display.warn(f"API login failed: {resp.status_code}")
        except Exception as e:
            self.display.warn(f"API unreachable: {e}")

    def _detect_pipeline_modules(self, ctx: TestContext) -> None:
        """Try importing each pipeline module and record availability."""
        import sys
        root = str(self.cfg.project_root)
        if root not in sys.path:
            sys.path.insert(0, root)

        modules_to_check = {
            "ocr": "pipeline.ocr_mrz",
            "tamper": "pipeline.tamper",
            "deepfake": "pipeline.deepfake",
            "face_match": "pipeline.face_match",
            "liveness": "pipeline.liveness",
            "physical_forgery": "pipeline.physical_forgery",
            "document_quality": "pipeline.document_quality",
            "security_zones": "pipeline.security_zones",
            "risk_engine": "pipeline.risk_engine",
            "gemini_scanner": "pipeline.gemini_scanner",
            "demographic": "pipeline.demographic",
            "watchlist": "pipeline.watchlist",
        }
        available: Dict[str, bool] = {}
        for name, mod_path in modules_to_check.items():
            try:
                __import__(mod_path)
                available[name] = True
            except Exception:
                available[name] = False

        ctx.available_modules = available
        avail_count = sum(available.values())
        self.display.info(f"Pipeline modules available: {avail_count}/{len(available)}")

    def _check_preconditions(self, entry: TestEntry, ctx: TestContext) -> Optional[str]:
        """Return a skip reason if preconditions aren't met."""
        if entry.requires_api and not ctx.api_token:
            try:
                import httpx
                url = self.cfg.api_base_url + "/api/health"
                resp = httpx.get(url, timeout=5)
                if resp.status_code != 200:
                    return f"API not reachable: {resp.status_code}"
            except Exception as e:
                return f"API not reachable: {e}"

        if entry.requires_pipeline:
            if not any(ctx.available_modules.values()):
                return "No pipeline modules available"

        return None

    def _new_category(self, entry: TestEntry, tests: List[TestEntry]) -> bool:
        """Returns True only for the first test in a new category."""
        idx = tests.index(entry)
        return idx == 0 or tests[idx - 1].category != entry.category

    def _run_analysis(self, run_result: RunResult) -> None:
        """Run bottleneck detection and memory analysis."""
        try:
            from ..analysis.bottleneck import detect_bottlenecks
            findings = detect_bottlenecks(run_result, self.cfg)
            run_result.bottleneck_findings = findings
            for f in findings:
                self.display.info(f"⚠ Bottleneck: {f}")
        except Exception as e:
            self.display.warn(f"Analysis error: {e}")

        try:
            from ..analysis.memory_leak import analyze_memory_growth
            if run_result.hardware_samples:
                analysis = analyze_memory_growth(run_result.hardware_samples, self.cfg)
                run_result.memory_analysis = analysis
                if analysis.suspected_leak:
                    self.display.warn(f"Suspected memory growth: slope={analysis.slope_mb_per_100req:.2f} MB/100req")
        except Exception as e:
            self.display.warn(f"Memory analysis error: {e}")

    def _run_visualization(self, run_result: RunResult) -> None:
        """Generate all charts."""
        try:
            from ..visualization.system_charts import generate_system_charts
            generate_system_charts(run_result, self.cfg)
        except Exception as e:
            self.display.warn(f"System charts error: {e}")

        try:
            from ..visualization.performance_charts import generate_performance_charts
            generate_performance_charts(run_result, self.cfg)
        except Exception as e:
            self.display.warn(f"Performance charts error: {e}")

        try:
            from ..visualization.ai_charts import generate_ai_charts
            generate_ai_charts(run_result, self.cfg)
        except Exception as e:
            self.display.warn(f"AI charts error: {e}")

        try:
            from ..visualization.load_charts import generate_load_charts
            generate_load_charts(run_result, self.cfg)
        except Exception as e:
            self.display.warn(f"Load charts error: {e}")

        try:
            from ..visualization.stability_charts import generate_stability_charts
            generate_stability_charts(run_result, self.cfg)
        except Exception as e:
            self.display.warn(f"Stability charts error: {e}")

        try:
            from ..visualization.diagrams import generate_architecture_diagram
            generate_architecture_diagram(run_result, self.cfg)
        except Exception as e:
            self.display.warn(f"Diagram error: {e}")

    def _run_reporting(self, run_result: RunResult) -> List[Path]:
        """Generate final reports in all configured formats."""
        paths: List[Path] = []
        try:
            from ..reporting.html_renderer import render_html_report
            html_path = render_html_report(run_result, self.cfg)
            if html_path:
                paths.append(html_path)
        except Exception as e:
            self.display.warn(f"HTML report error: {e}")

        try:
            from ..reporting.json_exporter import export_json, export_csv
            jp = export_json(run_result, self.cfg)
            cp = export_csv(run_result, self.cfg)
            if jp:
                paths.append(jp)
            if cp:
                paths.append(cp)
        except Exception as e:
            self.display.warn(f"JSON/CSV export error: {e}")

        return paths
