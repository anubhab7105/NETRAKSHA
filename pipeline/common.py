"""Shared helpers for the ML/CV pipeline modules.

Defines the single result contract every module returns, plus small
utilities for reading images, saving evidence files, and resolving the
vendored OCR runtime. Kept deliberately free of model/algorithm logic.
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = pathlib.Path(__file__).resolve().parent
_VENDOR = _ROOT / "vendor"

# Where module evidence images are written. Environment-overridable so tests
# and deployers can point at real object storage / app storage.
# Treat a blank SCREEN_EVIDENCE_DIR the same as unset — an empty value would
# otherwise resolve to "." (the process working directory) and litter the
# project root with evidence PNGs (audit P1 §6).
_evidence_env = os.environ.get("SCREEN_EVIDENCE_DIR", "").strip()
EVIDENCE_DIR = pathlib.Path(
    _evidence_env
    if _evidence_env
    else str(_ROOT.parent / "samples" / "evidence")
)

# InsightFace model root (buffalo_l pack). insightface appends `/models` to
# this root, so the pack must live at <root>/models/buffalo_l/.
INSIGHTFACE_MODEL_ROOT = (_VENDOR / "models").resolve()

# Vendored Tesseract runtime (binary + shared libs + tessdata).
_TESS_DIR = _VENDOR / "tesseract"
TESSERACT_BIN = _TESS_DIR / "tesseract"
TESS_LIB_DIR = _TESS_DIR
TESS_TESSDATA = _TESS_DIR / "tessdata"


def ensure_evidence_dir() -> pathlib.Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    return EVIDENCE_DIR


def new_evidence_path(module: str, ext: str = "png") -> pathlib.Path:
    """Return a fresh, unique evidence file path under the evidence dir."""
    ensure_evidence_dir()
    name = f"{module}_{uuid.uuid4().hex[:10]}.{ext.lstrip('.')}"
    return EVIDENCE_DIR / name


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------


@dataclass
class ModuleResult:
    """Contract returned by every pipeline module.

    Mirrors the ``module_results`` table in Shema.md so a caller (FastAPI route)
    can drop it straight into storage:

        module_name : str   e.g. "ocr", "tamper", "deepfake", "face_match", "liveness"
        score       : float|None 0-1, or None when inconclusive
        status      : str   "ok" | "inconclusive"
        raw_output  : dict  full per-module evidence for the UI panels
        evidence_uri: str|None  path to an evidence image, or None
    """

    module_name: str
    score: Optional[float]
    status: str  # "ok" | "inconclusive"
    raw_output: dict = field(default_factory=dict)
    evidence_uri: Optional[str] = None

    def to_json(self) -> dict:
        return {
            "module_name": self.module_name,
            "score": self.score,
            "status": self.status,
            "raw_output": _json_safe(self.raw_output),
            "evidence_uri": self.evidence_uri,
        }

    def __repr__(self) -> str:  # compact, PII-free repr for logs
        return (
            f"ModuleResult({self.module_name!r}, score={self.score!r}, "
            f"status={self.status!r})"
        )


def ok_result(
    module_name: str,
    score: float,
    raw_output: Optional[dict] = None,
    evidence_uri: Optional[str] = None,
) -> ModuleResult:
    return ModuleResult(
        module_name=module_name,
        score=float(np.clip(score, 0.0, 1.0)),
        status="ok",
        raw_output=dict(raw_output or {}),
        evidence_uri=_rel_uri(evidence_uri),
    )


def inconclusive_result(module_name: str, reason: str) -> ModuleResult:
    """The mandated graceful-degradation branch — never raises."""
    return ModuleResult(
        module_name=module_name,
        score=None,
        status="inconclusive",
        raw_output={
            "error": "inconclusive",
            "reason": _summarise_reason(reason),
        },
        evidence_uri=None,
    )


def _summarise_reason(reason: Any) -> str:
    """Short, generic reason string. Kept PII-free and truncated for logs."""
    if isinstance(reason, Exception):
        return f"{type(reason).__name__}: {str(reason)[:200]}"
    return str(reason)[:200]


def _rel_uri(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return str(path)


def _json_safe(obj: Any) -> Any:
    """Recursively convert numpy types / non-serialisable values for JSON."""
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return None if (np.isnan(obj) or np.isinf(obj)) else float(obj)
    if isinstance(obj, np.ndarray):
        return _json_safe(obj.tolist()) if obj.size <= 512 else f"<array {obj.shape}>"
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (pathlib.Path,)):
        return str(obj)
    return obj


def single_log(msg: str) -> None:
    """Placeholder structured logger. Extend with the team's logging lib later."""
    # Intentionally low-noise: modules should not emit PII. This no-op keeps
    # the boundary clean and swappable for a real logger.
    print(f"[pipeline] {msg}")


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------


def load_image(src: Any) -> np.ndarray:
    """Load an image into a BGR uint8 ndarray.

    Accepts a filesystem path (str/Path), a path-like, a URL-ish bytes buffer,
    a PIL Image, or an ndarray. Raises ValueError on unreadable input.
    """
    if isinstance(src, np.ndarray):
        return src.astype(np.uint8)

    if hasattr(src, "read"):  # file-like
        from PIL import Image as PILImage

        data = src.read()
        buf = np.frombuffer(data, dtype=np.uint8)
        import cv2

        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("could not decode image from buffer")
        return img

    if hasattr(src, "mode") and hasattr(src, "convert"):  # PIL Image
        import cv2

        rgb = np.asarray(src.convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    p = pathlib.Path(os.fspath(src))
    if not p.exists():
        raise FileNotFoundError(f"image not found: {p}")
    import cv2

    img = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"could not decode image: {p}")
    return img
