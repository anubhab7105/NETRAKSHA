
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


def ensure_evidence_dir() -> pathlib.Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    return EVIDENCE_DIR


def new_evidence_path(module: str, ext: str = "png") -> pathlib.Path:
    ensure_evidence_dir()
    name = f"{module}_{uuid.uuid4().hex[:10]}.{ext.lstrip('.')}"
    return EVIDENCE_DIR / name







@dataclass
class ModuleResult:

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
    return ModuleResult(
        module_name=module_name,
        score=float(np.clip(score, 0.0, 1.0)),
        status="ok",
        raw_output=dict(raw_output or {}),
        evidence_uri=_rel_uri(evidence_uri),
    )


def inconclusive_result(module_name: str, reason: str) -> ModuleResult:
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
    if isinstance(reason, Exception):
        return f"{type(reason).__name__}: {str(reason)[:200]}"
    return str(reason)[:200]


def _rel_uri(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return str(path)


def _json_safe(obj: Any) -> Any:
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


    print(f"[pipeline] {msg}")







def load_image(src: Any) -> np.ndarray:
    if isinstance(src, np.ndarray):
        return src.astype(np.uint8)

    if hasattr(src, "read"):
        from PIL import Image as PILImage

        data = src.read()
        buf = np.frombuffer(data, dtype=np.uint8)
        import cv2

        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("could not decode image from buffer")
        return img

    if hasattr(src, "mode") and hasattr(src, "convert"):
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
