"""JSON and CSV export for integration with CI/CD systems."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from ..core.config import FrameworkConfig
from ..core.models import RunResult


def export_json(run: RunResult, cfg: FrameworkConfig) -> Path:
    """Export complete run results as JSON."""
    out_path = cfg.output_dir / "reports" / f"netraksha_report_{run.metadata.run_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(run.to_json(indent=2), encoding="utf-8")
    return out_path


def export_csv(run: RunResult, cfg: FrameworkConfig) -> Path:
    """Export flattened results as CSV."""
    out_path = cfg.output_dir / "reports" / f"netraksha_results_{run.metadata.run_id}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Test Name", "Category", "Status", "Duration (ms)", "Errors", "Key Metrics"])
        
        for res in run.results:
            metric_summary = "; ".join(f"{k}={v}" for k, v in res.metrics.items() if not isinstance(v, (dict, list)))
            error_summary = "; ".join(res.errors)[:200]
            
            writer.writerow([
                res.test_name,
                res.category,
                res.status.value,
                f"{res.duration_ms:.2f}",
                error_summary,
                metric_summary
            ])
            
    return out_path
