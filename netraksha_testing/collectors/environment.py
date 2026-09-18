"""Environment snapshot for reproducibility."""

from __future__ import annotations

import platform
import subprocess
import sys
from typing import Any, Dict


def _get_git_commit(cwd: str = ".") -> str:
    """Get short git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=cwd, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _get_package_versions() -> Dict[str, str]:
    """Get versions of relevant packages."""
    packages = [
        "fastapi", "uvicorn", "sqlalchemy", "pydantic",
        "numpy", "opencv-python-headless", "insightface",
        "mediapipe", "onnxruntime", "pytesseract", "Pillow",
        "google-genai", "scikit-learn", "psutil",
        "httpx", "requests", "matplotlib", "plotly",
        "jinja2", "pyyaml",
    ]
    versions: Dict[str, str] = {}
    try:
        import importlib.metadata as _im
        for pkg in packages:
            try:
                versions[pkg] = _im.version(pkg)
            except Exception:
                versions[pkg] = "not_installed"
    except ImportError:
        pass
    return versions


def _get_netraksha_version() -> str:
    """Get Netraksha pipeline version."""
    try:
        from pipeline import __version__  # type: ignore
        return __version__
    except Exception:
        return "unknown"


def collect_environment(cfg: Any) -> Dict[str, Any]:
    """Collect a complete environment snapshot for reproducibility."""
    root = str(cfg.project_root) if hasattr(cfg, "project_root") else "."

    if root not in sys.path:
        sys.path.insert(0, root)

    return {
        "os_name": platform.system(),
        "os_version": platform.version(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "python_impl": platform.python_implementation(),
        "python_executable": sys.executable,
        "git_commit": _get_git_commit(cwd=root),
        "netraksha_pipeline_version": _get_netraksha_version(),
        "package_versions": _get_package_versions(),
        "platform_node": platform.node(),
    }
