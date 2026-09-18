"""HTML Report generation using Jinja2."""

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.config import FrameworkConfig
from ..core.models import RunResult


def render_html_report(run: RunResult, cfg: FrameworkConfig) -> Path:
    """Generate a single-file HTML report."""
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
    except ImportError:
        print("[reporting] Jinja2 not installed — skipping HTML report")
        return Path()
        
    template_dir = Path(__file__).parent / "templates"
    
    # Fallback to a basic template string if the file doesn't exist yet
    if not (template_dir / "report.html").exists():
        _create_basic_template(template_dir)
        
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(['html', 'xml'])
    )
    
    # Custom filters
    def b64image(filepath: str) -> str:
        """Embed image as base64 data URI."""
        p = Path(filepath)
        if not p.is_absolute():
            p = cfg.output_dir / "charts" / filepath
        if p.exists():
            with open(p, "rb") as f:
                data = base64.b64encode(f.read()).decode("utf-8")
                return f"data:image/png;base64,{data}"
        return ""
        
    def severity_color(sev: str) -> str:
        colors = {
            "CRITICAL": "#EF4444", "HIGH": "#F97316", "MEDIUM": "#F59E0B",
            "LOW": "#3B82F6", "INFO": "#6B7280"
        }
        return colors.get(sev, "#6B7280")
        
    def status_color(status: str) -> str:
        colors = {
            "PASS": "#10B981", "FAIL": "#EF4444", "ERROR": "#EF4444",
            "SKIPPED": "#F59E0B", "NOT_AVAILABLE": "#6B7280"
        }
        return colors.get(status, "#6B7280")
        
    env.filters['b64image'] = b64image
    env.filters['severity_color'] = severity_color
    env.filters['status_color'] = status_color
    
    template = env.get_template("report.html")
    
    # Prepare data for template
    html = template.render(
        run=run.to_dict(),
        run_obj=run,
        cfg=cfg.to_dict(),
        date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        embed_charts=cfg.embed_charts
    )
    
    out_path = cfg.output_dir / "reports" / f"netraksha_report_{run.metadata.run_id}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    
    return out_path


def _create_basic_template(template_dir: Path) -> None:
    """Create a basic template if one doesn't exist."""
    template_dir.mkdir(parents=True, exist_ok=True)
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Netraksha Test Report</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; max-width: 1200px; margin: 0 auto; padding: 20px; }
            h1, h2, h3 { color: #1e293b; }
            .header { background: linear-gradient(135deg, #1e293b, #334155); color: white; padding: 30px; border-radius: 8px; margin-bottom: 30px; }
            .header h1 { color: white; margin-top: 0; }
            table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e2e8f0; }
            th { background-color: #f8fafc; font-weight: 600; }
            .card { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
            .badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; color: white; }
            .img-container { margin: 20px 0; text-align: center; }
            .img-container img { max-width: 100%; height: auto; border: 1px solid #e2e8f0; border-radius: 4px; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Netraksha System Test Report</h1>
            <p>Run ID: {{ run.metadata.run_id }} | Date: {{ date }}</p>
        </div>
        
        <div class="card">
            <h2>1. Executive Summary</h2>
            <p>Total Tests: <b>{{ run.summary.total }}</b> | Passed: <b style="color:#10B981">{{ run.summary.passed }}</b> | Failed: <b style="color:#EF4444">{{ run.summary.failed }}</b></p>
        </div>
        
        <div class="card">
            <h2>2. Test Results</h2>
            <table>
                <tr><th>Test Name</th><th>Category</th><th>Status</th><th>Duration</th></tr>
                {% for res in run.results %}
                <tr>
                    <td>{{ res.test_name }}</td>
                    <td>{{ res.category }}</td>
                    <td><span class="badge" style="background-color: {{ res.status|status_color }}">{{ res.status }}</span></td>
                    <td>{{ "%.1f"|format(res.duration_ms) }} ms</td>
                </tr>
                {% endfor %}
            </table>
        </div>
        
        {% if embed_charts %}
        <div class="card">
            <h2>3. Resource Visualization</h2>
            <div class="img-container">
                <img src="{{ 'sys_cpu.png'|b64image }}" alt="CPU Usage" onerror="this.style.display='none'">
            </div>
            <div class="img-container">
                <img src="{{ 'sys_ram.png'|b64image }}" alt="RAM Usage" onerror="this.style.display='none'">
            </div>
            <div class="img-container">
                <img src="{{ 'perf_pipeline_breakdown.png'|b64image }}" alt="Pipeline Breakdown" onerror="this.style.display='none'">
            </div>
        </div>
        {% endif %}
    </body>
    </html>
    """
    (template_dir / "report.html").write_text(html, encoding="utf-8")
