"""Iris quality assessment."""

from __future__ import annotations
import cv2
import numpy as np
from typing import Dict, Any

def assess_iris_quality(eye_bgr) -> Dict[str, Any]:
    """Check blur, illumination, iris area, reflections."""
    try:
        from pipeline.common import load_image
        bgr = load_image(eye_bgr) if not isinstance(eye_bgr, np.ndarray) else eye_bgr
    except Exception as e:
        return {"quality": 0.0, "usable": False, "issues": ["unreadable"], "reason": str(e)[:60]}
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    issues = []
    # Resolution
    if min(h,w) < 80:
        issues.append("low_resolution")
    # Blur
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if sharp < 20:
        issues.append("blurry")
    # Illumination
    mean_v = float(cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[:,:,2].mean())
    if mean_v < 40:
        issues.append("too_dark")
    if mean_v > 220:
        issues.append("too_bright")
    # Iris area will be checked after segmentation; for now, basic
    quality = 0.9 if not issues else max(0.2, 0.9 - len(issues)*0.2)
    return {
        "quality": round(quality, 2),
        "usable": len(issues) == 0,
        "issues": issues,
        "metrics": {"sharpness": round(sharp,1), "mean_v": round(mean_v,1), "width": w, "height": h},
    }
