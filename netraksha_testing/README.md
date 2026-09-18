# Netraksha Testing & Benchmarking Framework

A comprehensive, modular Python testing and benchmarking framework built specifically for the Netraksha AI-Based Fake Identity & Document Screening System.

## Features

- **Automated Discovery**: Dynamically discovers and runs tests based on decorators.
- **Robust Orchestration**: The test runner is strictly non-destructive. Any failures in test logic are caught and logged without crashing the entire run.
- **Performance Benchmarking**:
  - Direct pipeline module invocation and latency tracking (Cold vs. Warm start).
  - API concurrency ramping and throughput analysis using `httpx` and `asyncio`.
- **System Monitoring**: Background threads to sample CPU, RAM, and Disk IO. Tracks process-specific memory via `psutil`.
- **Automated Analysis**:
  - Memory leak detection via linear regression on RAM usage over time.
  - Bottleneck detection against configurable thresholds.
- **Reporting & Visualization**:
  - Generates an interactive HTML report with embedded Base64 `matplotlib` charts.
  - Auto-generates architecture diagrams using Mermaid.
  - Exports raw metrics to JSON and flattened data to CSV.

## Project Structure

```
netraksha_testing/
├── main.py                     # CLI entry point
├── config.yaml                 # Core configuration and thresholds
├── requirements.txt            # Framework dependencies
├── core/
│   ├── models.py               # Shared dataclasses (TestResult, MetricSet, etc.)
│   ├── config.py               # YAML loader and environment variable merger
│   ├── registry.py             # @register_test decorator and auto-discovery
│   ├── runner.py               # Test orchestrator
│   └── adapters.py             # Wrappers around actual Netraksha pipeline modules
├── collectors/                 
│   ├── hardware.py             # System hardware snapshot
│   ├── environment.py          # OS, Python, and Package versions
│   ├── resource_monitor.py     # Background CPU/RAM sampling
│   └── process_monitor.py      # Targeted tracking of the uvicorn process
├── suites/
│   ├── ai_accuracy.py          # Face Verification FAR/FRR testing
│   ├── api_performance.py      # HTTP endpoint benchmarking
│   ├── concurrency_test.py     # API load and ramp testing
│   ├── database_test.py        # DB latency simulation via API
│   ├── failure_recovery.py     # Graceful degradation checks
│   ├── liveness_test.py        # MediaPipe liveness testing
│   ├── network_test.py         # Payload handling checks
│   ├── ocr_test.py             # OCR extraction accuracy
│   ├── pipeline_benchmark.py   # Direct python module benchmarking
│   ├── security_checks.py      # Headers, Auth enforcement, and Secret scanning
│   ├── stability_test.py       # Long running soak tests
│   └── tamper_test.py          # ELA and clone detection tests
├── analysis/
│   ├── bottleneck.py           # Threshold-based bottleneck detection
│   └── comparison.py           # Diffing two run outputs
├── visualization/
│   ├── theme.py                # Shared plotting styles (colors, fonts)
│   ├── system_charts.py        # Resource charts
│   ├── performance_charts.py   # Latency histograms and breakdowns
│   └── diagrams.py             # Architecture diagram generation
├── reporting/
│   ├── html_renderer.py        # Jinja2 template rendering
│   └── json_exporter.py        # CI/CD integration formats
└── utils/                      # Shared helpers
```

## Quick Start

### 1. Install Dependencies

Ensure you activate your virtual environment, then install the framework-specific requirements (which are kept isolated from the main Netraksha requirements where possible):

```bash
pip install -r requirements.txt
```

### 2. Configure Settings

Configuration is managed via `config.yaml`. By default, it points to local APIs (`http://127.0.0.1:8000`) and the `../samples` directory for dataset fixtures.

**Important:** Do not store passwords in `config.yaml`. Set the `TEST_PASSWORD` environment variable before running tests that require authentication:

```powershell
$env:TEST_PASSWORD="YourPasswordHere"
```

### 3. Run the Framework

Use the CLI to run specific categories or everything at once.

Run everything:
```bash
python main.py --all
```

Run only AI and Performance tests:
```bash
python main.py --category ai --category performance
```

Run with verbose logging:
```bash
python main.py --all -v
```

### 4. View Reports

After a successful run, navigate to the `output/` directory (or wherever configured in `config.yaml`).

- **Reports**: `output/reports/netraksha_report_<RUN_ID>.html` (Open in any browser)
- **Charts**: `output/charts/` (PNG images)
- **Raw Data**: `output/raw/<RUN_ID>.json`

## Adding New Tests

To add a new test, simply create a function in the appropriate module under `suites/` and decorate it with `@register_test`.

```python
from netraksha_testing.core.registry import register_test, CATEGORY_PERFORMANCE
from netraksha_testing.core.models import TestResult, TestStatus

@register_test(
    category=CATEGORY_PERFORMANCE,
    name="my_custom_test",
    description="Brief description of what this checks"
)
def my_custom_test(cfg, ctx) -> TestResult:
    # Test logic here...
    return TestResult(
        test_name="my_custom_test",
        category=CATEGORY_PERFORMANCE,
        status=TestStatus.PASS,
        duration_ms=15.5
    )
```

The runner will automatically discover the test and include it in the execution flow.
