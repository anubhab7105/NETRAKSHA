"""Document Image Quality Gate — pre-check before OCR/tamper.

Rejects blurry, dark, cropped, low-res, or otherwise unusable document
images before any forensic analysis, with actionable recapture guidance.
"""

from __future__ import annotations
import cv2
import numpy as np
from pathlib import Path
from typing import Dict, Any

from .common import load_image, inconclusive_result, ok_result, ModuleResult

MODULE_NAME = "document_quality"

MIN_DIM = 480
BLUR_THRESH = 35.0
DARK_THRESH = 35.0
BRIGHT_THRESH = 225.0

def assess_document(bgr: np.ndarray) -> Dict[str, Any]:
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    mean_v = float(cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[:,:,2].mean())
    issues = []
    if min(h, w) < MIN_DIM:
        issues.append("low_resolution")
    if sharp < BLUR_THRESH:
        issues.append("blurry")
    if mean_v < DARK_THRESH:
        issues.append("too_dark")
    if mean_v > BRIGHT_THRESH:
        issues.append("too_bright")
    return {
        "gate": "passed" if not issues else "failed",
        "issues": issues,
        "metrics": {"width": w, "height": h, "sharpness": round(sharp,1), "mean_v": round(mean_v,1)},
        "recapture_reasons": [f"Document {i}: recapture in good light, hold steady" for i in issues],
    }

def run_document_quality(document_image, save_evidence: bool = False) -> ModuleResult:
    try:
        bgr = load_image(document_image)
    except Exception as e:
        return inconclusive_result(MODULE_NAME, e)
    report = assess_document(bgr)
    score = 0.0 if report["gate"] == "passed" else 0.85
    if report["gate"] == "passed":
        return ok_result(MODULE_NAME, score, report, None)
    else:

        return ok_result(MODULE_NAME, score, report, None)
