"""Diagram generation using Mermaid."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.models import RunResult


def generate_architecture_diagram(run: RunResult, cfg: Any) -> Path:
    """Generate a Mermaid Markdown diagram of the architecture based on results."""
    
    # We can infer parts of the architecture based on what tests succeeded
    has_api = any(r.test_name.startswith("api_") and r.status.value != "NOT_AVAILABLE" for r in run.results)
    
    pipeline_res = next((r for r in run.results if r.test_name == "pipeline_module_benchmark"), None)
    available_modules = []
    if pipeline_res:
         available_modules = [k.replace("_status", "") for k, v in pipeline_res.metrics.items() if k.endswith("_status") and v == "AVAILABLE"]

    diagram = """```mermaid
graph TD
    Client[Client App] --> API[FastAPI Backend]
"""
    
    if has_api:
        diagram += "    API <--> DB[(Supabase PostgreSQL)]\n"
        
    diagram += "    API --> Pipeline{Analysis Pipeline}\n"
    
    for mod in available_modules:
         diagram += f"    Pipeline --> M_{mod}[{mod.replace('_', ' ').title()}]\n"
         
    diagram += "```\n"

    out_path = cfg.output_dir / "diagrams" / "architecture.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(diagram, encoding="utf-8")
    return out_path
