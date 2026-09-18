"""Configuration loader for the Netraksha Testing Framework.

Loads config.yaml and merges environment variables. Secrets are NEVER
stored in config files — they must come from environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

_DEFAULTS: Dict[str, Any] = {
    "api": {
        "base_url": "http://127.0.0.1:8000",
        "timeout": 30,
        "auth": {
            "username": "officer1",
            "password_env": "TEST_PASSWORD",  # env var name, not the password itself
        },
        "endpoints": {
            "health": "/api/health",
            "login": "/api/auth/login",
            "screen": "/api/screen",
            "cases": "/api/cases",
            "audit": "/api/audit",
        },
        "iterations": 10,
    },
    "pipeline": {
        "project_root": None,  # auto-detected if None
        "modules": {
            "ocr": {
                "enabled": True,
                "type": "python",
                "function": "pipeline.ocr_mrz.run_ocr_mrz",
            },
            "tamper": {
                "enabled": True,
                "type": "python",
                "function": "pipeline.tamper.run_tamper",
            },
            "deepfake": {
                "enabled": True,
                "type": "python",
                "function": "pipeline.deepfake.run_deepfake",
            },
            "face_match": {
                "enabled": True,
                "type": "python",
                "function": "pipeline.face_match.run_face_match",
            },
            "liveness": {
                "enabled": True,
                "type": "python",
                "function": "pipeline.liveness.run_liveness",
            },
            "physical_forgery": {
                "enabled": True,
                "type": "python",
                "function": "pipeline.physical_forgery.run_physical_forgery",
            },
            "document_quality": {
                "enabled": True,
                "type": "python",
                "function": "pipeline.document_quality.run_document_quality",
            },
        },
        "iterations": 5,
    },
    "concurrency": {
        "levels": [1, 2, 5, 10, 20],
        "requests_per_level": 20,
        "target_endpoint": "/api/health",
    },
    "stability": {
        "iterations": 100,
        "checkpoint_interval": 10,
    },
    "datasets": {
        "documents_genuine": "datasets/documents/genuine",
        "documents_tampered": "datasets/documents/tampered",
        "faces_dir": "datasets/faces",
        "face_genuine_pairs_csv": "datasets/faces/genuine_pairs.csv",
        "face_impostor_pairs_csv": "datasets/faces/impostor_pairs.csv",
        "liveness_genuine_dir": "datasets/liveness/genuine",
        "liveness_attack_dir": "datasets/liveness/attack",
        "ocr_images_dir": "datasets/ocr/images",
        "ocr_ground_truth_csv": "datasets/ocr/ground_truth.csv",
    },
    "thresholds": {
        "face_match": 0.55,
        "tamper_high": 0.7,
        "tamper_moderate": 0.4,
        "deepfake_high": 0.7,
        "liveness": 0.45,
        "cpu_bottleneck_pct": 80.0,
        "ram_bottleneck_pct": 85.0,
        "memory_leak_slope_mb_per_100req": 0.5,
        "latency_regression_pct": 10.0,
        "throughput_regression_pct": 10.0,
    },
    "monitoring": {
        "sampling_interval_s": 0.5,
        "process_name": "uvicorn",
    },
    "reporting": {
        "formats": ["html", "json", "csv"],
        "charts_dpi": 150,
        "embed_charts_in_html": True,
        "pdf": False,
    },
    "output": {
        "directory": "output",
    },
    "security": {
        "scan_source_files": True,
        "check_headers": True,
        "check_auth": True,
        "check_input_validation": True,
    },
}


# ---------------------------------------------------------------------------
# FrameworkConfig
# ---------------------------------------------------------------------------

class FrameworkConfig:
    """Loaded and validated testing framework configuration."""

    def __init__(self, data: Dict[str, Any], base_dir: Path):
        self._data = data
        self.base_dir = base_dir

    def get(self, *keys: str, default: Any = None) -> Any:
        """Navigate nested config with dot-path keys."""
        current = self._data
        for key in keys:
            if not isinstance(current, dict):
                return default
            current = current.get(key, default if key == keys[-1] else {})
        return current

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def api_base_url(self) -> str:
        return self.get("api", "base_url", default="http://127.0.0.1:8000")

    @property
    def api_timeout(self) -> int:
        return int(self.get("api", "timeout", default=30))

    @property
    def api_username(self) -> str:
        return self.get("api", "auth", "username", default="officer1")

    @property
    def api_password(self) -> Optional[str]:
        """Read password from environment variable — never from config."""
        env_var = self.get("api", "auth", "password_env", default="TEST_PASSWORD")
        return os.environ.get(env_var)

    @property
    def api_endpoints(self) -> Dict[str, str]:
        return self.get("api", "endpoints", default={})

    @property
    def api_iterations(self) -> int:
        return int(self.get("api", "iterations", default=10))

    @property
    def pipeline_iterations(self) -> int:
        return int(self.get("pipeline", "iterations", default=5))

    @property
    def pipeline_modules(self) -> Dict[str, Any]:
        return self.get("pipeline", "modules", default={})

    @property
    def project_root(self) -> Path:
        """Auto-detect Netraksha project root (parent of netraksha_testing/)."""
        configured = self.get("pipeline", "project_root")
        if configured:
            return Path(configured)
        # The testing framework lives inside the Netraksha project
        return self.base_dir.parent

    @property
    def concurrency_levels(self) -> List[int]:
        return self.get("concurrency", "levels", default=[1, 2, 5, 10])

    @property
    def concurrency_requests_per_level(self) -> int:
        return int(self.get("concurrency", "requests_per_level", default=20))

    @property
    def stability_iterations(self) -> int:
        return int(self.get("stability", "iterations", default=100))

    @property
    def stability_checkpoint_interval(self) -> int:
        return int(self.get("stability", "checkpoint_interval", default=10))

    @property
    def thresholds(self) -> Dict[str, float]:
        return self.get("thresholds", default={})

    def threshold(self, name: str) -> float:
        return float(self.get("thresholds", name,
                              default=_DEFAULTS["thresholds"].get(name, 0.0)))

    @property
    def sampling_interval(self) -> float:
        return float(self.get("monitoring", "sampling_interval_s", default=0.5))

    @property
    def output_dir(self) -> Path:
        raw = self.get("output", "directory", default="output")
        p = Path(raw)
        if not p.is_absolute():
            p = self.base_dir / p
        return p

    def dataset_path(self, name: str) -> Path:
        raw = self.get("datasets", name, default="")
        if not raw:
            return Path(".")
        p = Path(raw)
        if not p.is_absolute():
            p = self.base_dir / p
        return p

    @property
    def report_formats(self) -> List[str]:
        return self.get("reporting", "formats", default=["html", "json", "csv"])

    @property
    def charts_dpi(self) -> int:
        return int(self.get("reporting", "charts_dpi", default=150))

    @property
    def embed_charts(self) -> bool:
        return bool(self.get("reporting", "embed_charts_in_html", default=True))

    def to_dict(self) -> Dict[str, Any]:
        """Return a sanitized copy of the config (secrets redacted)."""
        import copy
        d = copy.deepcopy(self._data)
        # Redact any password-like keys
        _redact_keys = {"password", "secret", "token", "key", "api_key"}
        def _redact(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {k: "[REDACTED]" if any(r in k.lower() for r in _redact_keys)
                        else _redact(v) for k, v in obj.items()}
            return obj
        return _redact(d)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Recursively merge override into base."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_config(config_path: Optional[Path] = None) -> FrameworkConfig:
    """Load framework configuration.

    Priority (highest to lowest):
    1. Explicit config_path argument
    2. NETRAKSHA_TEST_CONFIG environment variable
    3. config.yaml in the netraksha_testing/ directory
    4. Built-in defaults

    Args:
        config_path: Optional explicit path to config.yaml

    Returns:
        FrameworkConfig instance with merged configuration.
    """
    # Determine base directory (the netraksha_testing/ directory)
    base_dir = Path(__file__).resolve().parent.parent

    data = dict(_DEFAULTS)

    # Determine config file path
    if config_path is None:
        env_path = os.environ.get("NETRAKSHA_TEST_CONFIG", "")
        if env_path:
            config_path = Path(env_path)
        else:
            candidates = [
                base_dir / "config.yaml",
                base_dir / "config.yml",
            ]
            for c in candidates:
                if c.exists():
                    config_path = c
                    break

    # Load YAML if found
    if config_path and config_path.exists():
        if not _HAS_YAML:
            print("[config] WARNING: PyYAML not installed — using defaults only")
        else:
            with open(config_path, "r", encoding="utf-8") as f:
                file_data = yaml.safe_load(f) or {}
            data = _deep_merge(data, file_data)

    return FrameworkConfig(data, base_dir)
