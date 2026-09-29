
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

