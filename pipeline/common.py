"""Shared helpers for the ML/CV pipeline modules.

Defines the single result contract every module returns, plus small
utilities for reading images, saving evidence files, and resolving the
vendored OCR runtime. Kept deliberately free of model/algorithm logic.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

import numpy as np





_ROOT = pathlib.Path(__file__).resolve().parent
_VENDOR = _ROOT / "vendor"






_evidence_env = os.environ.get("SCREEN_EVIDENCE_DIR", "").strip()
EVIDENCE_DIR = pathlib.Path(
    _evidence_env
    if _evidence_env
    else str(_ROOT.parent / "samples" / "evidence")
)



INSIGHTFACE_MODEL_ROOT = (_VENDOR / "models").resolve()


_THRESHOLDS_CACHE: Optional[dict] = None


# Env-var overrides for the single thresholds source of truth. Each key may
# be overridden via PIPELINE_<UPPER_KEY>, e.g. PIPELINE_FACE_MATCH=0.6.
# Legacy per-module names are honoured where they already exist in the wild.
_THRESHOLD_ENV_ALIASES = {
    "face_match": ("PIPELINE_FACE_MATCH", "FACE_MATCH_THRESHOLD"),
    "face_low_conf_low": ("PIPELINE_FACE_LOW_CONF_LOW",),
    "face_low_conf_high": ("PIPELINE_FACE_LOW_CONF_HIGH",),
    "tamper_high": ("PIPELINE_TAMPER_HIGH",),
    "tamper_moderate": ("PIPELINE_TAMPER_MODERATE",),
    "physical_high": ("PIPELINE_PHYSICAL_HIGH", "PHYS_HIGH"),
    "physical_moderate": ("PIPELINE_PHYSICAL_MODERATE", "PHYS_MODERATE"),
    "deepfake_high": ("PIPELINE_DEEPFAKE_HIGH",),
    "liveness": ("PIPELINE_LIVENESS", "LIVENESS_THRESHOLD"),
    "name_match": ("PIPELINE_NAME_MATCH",),
    "address_match": ("PIPELINE_ADDRESS_MATCH",),
    "risk_red": ("PIPELINE_RISK_RED",),
    "risk_yellow": ("PIPELINE_RISK_YELLOW",),
    "watchlist_fuzzy": ("PIPELINE_WATCHLIST_FUZZY",),
    "document_quality_blur": ("PIPELINE_DOC_QUALITY_BLUR",),
    "document_quality_dark": ("PIPELINE_DOC_QUALITY_DARK",),
    "iris_match": ("PIPELINE_IRIS_MATCH",),
    "iris_low_conf_low": ("PIPELINE_IRIS_LOW_CONF_LOW",),
    "iris_low_conf_high": ("PIPELINE_IRIS_LOW_CONF_HIGH",),
}


def _apply_threshold_env_overrides(merged: dict) -> dict:
    for key, names in _THRESHOLD_ENV_ALIASES.items():
        for env_name in names:
            raw = os.environ.get(env_name)
            if raw is None or str(raw).strip() == "":
                continue
            try:
                merged[key] = float(str(raw).strip())
            except (TypeError, ValueError):
                pass
            break
    return merged


def reload_thresholds() -> dict:
    """Force re-read of thresholds.json + env overrides (tests use this)."""
    global _THRESHOLDS_CACHE
    _THRESHOLDS_CACHE = None
    return load_thresholds()


def load_thresholds() -> dict:
    """Load pipeline/thresholds.json (cached). Missing file/keys fall back to code defaults.

    This is the single source of truth for decision thresholds — modules must
    read their band through here instead of hardcoding magic numbers.
    Env vars (see _THRESHOLD_ENV_ALIASES) override file values.
    """
    global _THRESHOLDS_CACHE
    if _THRESHOLDS_CACHE is not None:
        return _THRESHOLDS_CACHE
    defaults = {
        "face_match": 0.55,
        "face_low_conf_low": 0.45,
        "face_low_conf_high": 0.65,
        "tamper_high": 0.7,
        "tamper_moderate": 0.4,
        "physical_high": 0.7,
        "physical_moderate": 0.4,
        "deepfake_high": 0.7,
        "liveness": 0.45,
        "name_match": 0.85,
        "address_match": 0.60,
        "risk_red": 0.65,
        "risk_yellow": 0.35,
        "watchlist_fuzzy": 0.8,
        "document_quality_blur": 35.0,
        "document_quality_dark": 35.0,
        "iris_match": 0.32,
        "iris_low_conf_low": 0.28,
        "iris_low_conf_high": 0.36,
    }
    try:
        with open(_ROOT / "thresholds.json", "r", encoding="utf-8") as fh:
            file_values = json.load(fh)
        merged = {**defaults, **{k: v for k, v in file_values.items() if k in defaults}}
        # Iris thresholds are prototype placeholders (see thresholds.json
        # calibration_note) — never silently adopt them without the marker.
    except Exception:
        merged = dict(defaults)
    merged = _apply_threshold_env_overrides(merged)
    _THRESHOLDS_CACHE = merged
    return merged




_TESS_DIR = _VENDOR / "tesseract"

_SYSTEM_TESSDATA = None
for _cand in (
    "/usr/share/tesseract-ocr/5/tessdata",
    "/usr/share/tesseract-ocr/4.00/tessdata",
    "/usr/share/tessdata",
    "/opt/homebrew/share/tessdata",
):
    if (pathlib.Path(_cand) / "eng.traineddata").exists():
        _SYSTEM_TESSDATA = pathlib.Path(_cand)
        break




_SYSTEM_TESSBIN = None
if _SYSTEM_TESSDATA is None:
    _win_candidates = [shutil.which("tesseract")]
    # Configurable override (cross-platform): TESSERACT_CMD may point at the
    # binary directly, e.g. C:\Program Files\Tesseract-OCR\tesseract.exe.
    # Checked before the standard Windows install path below.
    _env_tess = (os.environ.get("TESSERACT_CMD") or "").strip().strip('"')
    if _env_tess:
        _win_candidates.insert(0, _env_tess)
    for _pf in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        _win_candidates.append(str(pathlib.Path(_pf) / "Tesseract-OCR" / "tesseract.exe"))
    for _b in _win_candidates:
        if _b and pathlib.Path(_b).is_file():
            _td = pathlib.Path(_b).parent / "tessdata"
            if (_td / "eng.traineddata").is_file():
                _SYSTEM_TESSBIN = pathlib.Path(_b)
                _SYSTEM_TESSDATA = _td
                break

if (_TESS_DIR / "tesseract").exists() and (_TESS_DIR / "tessdata" / "eng.traineddata").exists():
    TESSERACT_BIN = _TESS_DIR / "tesseract"
    TESS_LIB_DIR = _TESS_DIR
    TESS_TESSDATA = _TESS_DIR / "tessdata"
elif (_sys_tess := _SYSTEM_TESSBIN or shutil.which("tesseract")) and _SYSTEM_TESSDATA:
    TESSERACT_BIN = pathlib.Path(_sys_tess)
    TESS_LIB_DIR = TESSERACT_BIN.parent
    TESS_TESSDATA = _SYSTEM_TESSDATA
else:
    TESSERACT_BIN = _TESS_DIR / "tesseract"
    TESS_LIB_DIR = _TESS_DIR
    TESS_TESSDATA = _TESS_DIR / "tessdata"


def get_evidence_dir() -> pathlib.Path:
    """Resolve the evidence dir fresh (honours late env changes in tests)."""
    env = os.environ.get("SCREEN_EVIDENCE_DIR", "").strip()
    return pathlib.Path(env) if env else EVIDENCE_DIR


def ensure_evidence_dir() -> pathlib.Path:
    path = get_evidence_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_evidence_path(module: str, ext: str = "png") -> pathlib.Path:
    """Return a fresh, unique evidence file path under the evidence dir."""
    base = ensure_evidence_dir()
    name = f"{module}_{uuid.uuid4().hex[:10]}.{ext.lstrip('.')}"
    return base / name







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
    status: str
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

    def __repr__(self) -> str:
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
    try:
        value = float(score)
    except (TypeError, ValueError):
        return inconclusive_result(module_name, f"non-numeric score: {score!r}"[:200])
    if value != value or value in (float("inf"), float("-inf")):
        return inconclusive_result(module_name, f"non-finite score: {score!r}"[:200])
    return ModuleResult(
        module_name=module_name,
        score=float(np.clip(value, 0.0, 1.0)),
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
        text = f"{type(reason).__name__}: {str(reason)}"
    else:
        text = str(reason)
    text = text.replace(str(_ROOT.parent), "<root>").replace(str(_ROOT), "<pipeline>")
    return text[:200]


def _rel_uri(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        # Prefer a repo-relative URI (no absolute server path in API/DB
        # payloads; backend resolves via basename and tests can still
        # Path(uri).exists() from the repo root). Files written outside the
        # repo (e.g. pytest tmp_path evidence dirs) keep their absolute path
        # so existence checks still resolve.
        p = pathlib.Path(str(path))
        try:
            return str(p.resolve().relative_to(_ROOT.parent.resolve()))
        except Exception:
            return str(p)
    except Exception:
        return None


def _json_safe(obj: Any) -> Any:
    """Recursively convert numpy types / non-serialisable values for JSON."""
    import datetime as _dt

    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return [_json_safe(v) for v in sorted(obj, key=repr)]
    if isinstance(obj, (bytes, bytearray)):
        try:
            return {"__bytes_b64__": __import__("base64").b64encode(bytes(obj)).decode("ascii")}
        except Exception:
            return f"<bytes {len(bytes(obj))}>"
    if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
        try:
            return obj.isoformat()
        except Exception:
            return str(obj)
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


    print(f"[pipeline] {msg}")







def load_image(src: Any) -> np.ndarray:
    """Load an image into a BGR uint8 ndarray.

    Accepts a filesystem path (str/Path), a path-like, a URL-ish bytes buffer,
    a PIL Image, or an ndarray. Raises ValueError on unreadable input.
    Decompression bombs are rejected: source files over 50 MB or images
    over 100 megapixels raise ValueError (callers degrade to inconclusive).
    Channel contract: always returns HxWx3 BGR uint8 (2-D gray and 4-channel
    BGRA inputs are converted; anything else raises ValueError).
    """
    _MAX_FILE_BYTES = 50_000_000
    _MAX_PIXELS = 100_000_000
    if isinstance(src, np.ndarray):
        import cv2 as _cv2

        if src.size == 0:
            raise ValueError("empty image array")
        if src.size > _MAX_PIXELS:
            raise ValueError(f"image too large: {src.size} pixels")
        if src.ndim == 2:
            arr = np.ascontiguousarray(src, dtype=np.uint8)
            return _cv2.cvtColor(arr, _cv2.COLOR_GRAY2BGR)
        if src.ndim != 3 or src.shape[2] not in (3, 4):
            raise ValueError(f"unsupported channel count: {getattr(src, 'shape', None)}")
        if src.shape[2] == 4:
            arr = np.ascontiguousarray(src, dtype=np.uint8)
            return _cv2.cvtColor(arr, _cv2.COLOR_BGRA2BGR)
        if src.dtype != np.uint8:
            arr = np.clip(np.asarray(src, dtype=np.float64), 0, 255).astype(np.uint8)
        else:
            arr = np.ascontiguousarray(src)
        if arr.size > _MAX_PIXELS:
            raise ValueError(f"image too large: {arr.size} pixels")
        return arr

    if hasattr(src, "read"):
        from PIL import Image as PILImage

        data = src.read()
        if len(data) > _MAX_FILE_BYTES:
            raise ValueError("image buffer too large")
        buf = np.frombuffer(data, dtype=np.uint8)
        import cv2

        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("could not decode image from buffer")
        if img.size > _MAX_PIXELS:
            raise ValueError(f"image too large: {img.size} pixels")
        return img

    if hasattr(src, "mode") and hasattr(src, "convert"):
        import cv2

        rgb = np.asarray(src.convert("RGB"))
        if rgb.size > _MAX_PIXELS:
            raise ValueError(f"image too large: {rgb.size} pixels")
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    p = pathlib.Path(os.fspath(src))
    if not p.exists():
        raise FileNotFoundError(f"image not found: {p}")
    try:
        if p.stat().st_size > _MAX_FILE_BYTES:
            raise ValueError(f"image file too large: {p.stat().st_size} bytes")
    except OSError as exc:
        raise ValueError(f"cannot stat image: {p}") from exc
    import cv2

    img = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"could not decode image: {p}")
    if img.size > _MAX_PIXELS:
        raise ValueError(f"image too large: {img.size} pixels")
    return img
