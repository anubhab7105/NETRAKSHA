"""AI Document Screening — ML / CV pipeline package.

Fifteen isolated, independently callable modules:

    ocr_mrz            OCR / MRZ extraction (Tesseract + ICAO 9303 checksum)
    checksums          Algorithmic validators (Verhoeff, ICAO, PAN, EPIC)
    demographic        Database demographic reconciliation
    tamper             Tamper detection (ELA + SHA1 exact-duplicate copy-move, < 1.5s)
    physical_forgery   Layout / MRZ-font / photo-frame / moiré / QR checks
    deepfake           Deepfake detection (FFT frequency-artifact heuristic)
    face_match         Face match 3-way (InsightFace/ArcFace cosine similarity, local-authoritative)
    face_quality       Capture/face quality gates (used by face_match)
    document_quality   Blur/brightness gates
    liveness           Liveness (blink / eye-aspect-ratio over a frame burst)
    gemini_scanner     Single-call Gemini AI multi-task scanner
    watchlist          Watchlist provider (mock/real)
    risk_engine        Rule-based composite risk assessment
    security_zones     Legacy zone ROIs (superseded, still run)
    fairness           In-memory fairness ledger + report

Every module obeys the hard "never crash" contract: any internal failure is
caught and returned as ``status="inconclusive"`` with ``score=None``. No module
produces an approve/deny verdict — that decision belongs to the Risk Engine and
the human officer.
"""

__version__ = "0.1.0"

import warnings as _warnings

# AUD-06: narrow, documented suppression of known third-party deprecation
# FutureWarnings. insightface 2.0 and PassportEye 2.2.2 are installed
# dependencies (site-packages — not vendored, not project-owned), so their
# internal scikit-image calls cannot be migrated in-repo:
#   * insightface/utils/face_align.py uses SimilarityTransform.estimate()
#     (deprecated since scikit-image 0.26, removal in 2.2)
#   * passporteye/mrz/image.py uses skimage.morphology.square() (deprecated
#     since 0.25, removal in 0.27) and skimage.io.imread(plugin=...)
# Pinning scikit-image <0.25 was rejected (transitive downgrade with numpy-2
# compat risk). Each filter matches one exact message + module so genuine
# project warnings still surface.
for _msg, _mod in (
    (r"`estimate` is deprecated.*", "insightface\\.utils\\.face_align"),
    (r"`square` is deprecated.*", "passporteye\\.mrz\\.image"),
    # Emitted from passporteye/mrz/image.py (attributed to that module):
    # skimage.io plugin-infrastructure deprecation.
    (r".*plugin.*deprecated.*", "passporteye\\.mrz\\.image"),
):
    _warnings.filterwarnings(
        "ignore", message=_msg, category=FutureWarning, module=_mod
    )
del _msg, _mod
del _warnings

from .common import ModuleResult

_LAZY_MODULES = {
    "ocr_mrz",
    "tamper",
    "deepfake",
    "face_match",
    "liveness",
    "checksums",
    "gemini_scanner",
    "demographic",
    "watchlist",
    "risk_engine",
    "physical_forgery",
    "face_quality",
    "document_quality",
    "security_zones",
    "fairness",
}


def __getattr__(name: str):
    """Lazy submodule import — avoids pulling cv2/mediapipe/onnx at package import."""
    if name in _LAZY_MODULES:
        import importlib

        mod = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = mod
        return mod
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ModuleResult",
    "ocr_mrz",
    "tamper",
    "deepfake",
    "face_match",
    "liveness",
    "checksums",
    "gemini_scanner",
    "demographic",
    "watchlist",
    "risk_engine",
    "physical_forgery",
    "face_quality",
    "document_quality",
    "security_zones",
    "fairness",
    "__version__",
]
