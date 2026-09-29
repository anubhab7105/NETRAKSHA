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

from .common import ModuleResult
from . import ocr_mrz, tamper, deepfake, face_match, liveness
from . import checksums, gemini_scanner, demographic, watchlist, risk_engine
from . import physical_forgery, face_quality, document_quality, security_zones, fairness

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

