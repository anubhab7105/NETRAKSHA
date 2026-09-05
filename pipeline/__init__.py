"""AI Document Screening — ML / CV pipeline package.

Ten isolated, independently callable modules:

    Module 1  ocr_mrz.run_ocr_mrz        OCR / MRZ extraction (Tesseract + ICAO 9303 checksum)
    Module 2  tamper.run_tamper           Tamper detection (ELA + optimized copy-move, < 0.8s)
    Module 3  deepfake.run_deepfake       Deepfake detection (FFT frequency-artifact heuristic)
    Module 4  face_match.run_face_match   Face match 1:1 (InsightFace/ArcFace cosine similarity)
    Module 5  liveness.run_liveness       Liveness (blink / eye-aspect-ratio over a frame burst)
    Module 6  checksums                   Algorithmic validators (Verhoeff, ICAO, PAN, EPIC)
    Module 7  gemini_scanner              Single-call Gemini AI multi-task scanner
    Module 8  demographic                 Database demographic reconciliation
    Module 9  watchlist                   Watchlist provider (mock/real)
    Module 10 risk_engine                 Rule-based composite risk assessment

Every module obeys the hard "never crash" contract: any internal failure is
caught and returned as ``status="inconclusive"`` with ``score=None``. No module
produces an approve/deny verdict — that decision belongs to the Risk Engine and
the human officer.
"""

__version__ = "0.1.0"

from .common import ModuleResult
from . import ocr_mrz, tamper, deepfake, face_match, liveness
from . import checksums, gemini_scanner, demographic, watchlist, risk_engine

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
    "__version__",
]

