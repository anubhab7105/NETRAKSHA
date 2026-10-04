"""Document Image Quality Gate — pre-check before OCR/tamper.

Rejects blurry, dark, cropped, low-res, or otherwise unusable document
images before any forensic analysis, with actionable recapture guidance.
"""

from __future__ import annotations
import cv2
import numpy as np
from pathlib import Path
from typing import Dict, Any

from .common import load_image, inconclusive_result, ok_result, ModuleResult, load_thresholds

MODULE_NAME = "document_quality"

MIN_DIM = 480
BLUR_THRESH = 35.0
DARK_THRESH = 35.0
BRIGHT_THRESH = 225.0


def _quality_thresholds() -> tuple:
    try:
        _thr = load_thresholds()
        blur = float(_thr.get("document_quality_blur", BLUR_THRESH))
        dark = float(_thr.get("document_quality_dark", DARK_THRESH))
    except Exception:
        blur, dark = BLUR_THRESH, DARK_THRESH
    import os as _os

    try:
        blur = float(_os.environ.get("PIPELINE_DOC_QUALITY_BLUR", blur))
    except (TypeError, ValueError):
        pass
    try:
        dark = float(_os.environ.get("PIPELINE_DOC_QUALITY_DARK", dark))
    except (TypeError, ValueError):
        pass
    return blur, dark

def assess_document(bgr: np.ndarray) -> Dict[str, Any]:
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    mean_v = float(cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[:,:,2].mean())
    _blur_thr, _dark_thr = _quality_thresholds()
    issues = []
    if min(h, w) < MIN_DIM:
        issues.append("low_resolution")
    if sharp < _blur_thr:
        issues.append("blurry")
    if mean_v < _dark_thr:
        issues.append("too_dark")
    if mean_v > BRIGHT_THRESH:
        issues.append("too_bright")
    return {
        "gate": "passed" if not issues else "failed",
        "issues": issues,
        "metrics": {"width": w, "height": h, "sharpness": round(sharp,1), "mean_v": round(mean_v,1),
                    "blur_threshold": _blur_thr, "dark_threshold": _dark_thr},
        "recapture_reasons": [f"Document {i}: recapture in good light, hold steady" for i in issues],
    }

def run_document_quality(document_image, save_evidence: bool = False) -> ModuleResult:
    try:
        bgr = load_image(document_image)
    except Exception as e:
        return inconclusive_result(MODULE_NAME, e)
    report = assess_document(bgr)
    if report["gate"] == "passed":
        return ok_result(MODULE_NAME, 0.0, report, None)
    report["action"] = "recapture"
    return inconclusive_result(
        MODULE_NAME,
        f"document_quality_failed: {', '.join(report['issues'])} "
        f"({'; '.join(report['recapture_reasons'])})",
    )
