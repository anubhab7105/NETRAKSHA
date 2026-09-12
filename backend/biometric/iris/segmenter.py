"""Iris/pupil segmentation — classical Hough circles (CPU, no training)."""

from __future__ import annotations
import cv2
import numpy as np
from typing import Dict, Any

def segment_iris(eye_bgr: np.ndarray) -> Dict[str, Any]:
    """Segment iris and pupil via Hough circles on the eye crop."""
    try:
        gray = cv2.cvtColor(eye_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.medianBlur(gray, 5)
        h, w = gray.shape[:2]
        # Detect iris (limbus) — largest circle
        circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, 1, 20, param1=50, param2=30, minRadius=int(min(h,w)*0.15), maxRadius=int(min(h,w)*0.45))
        if circles is None:
            return {"status": "no_iris", "reason": "iris circle not found"}
        circles = np.uint16(np.around(circles))
        iris = circles[0][0]  # x,y,r
        ix, iy, ir = int(iris[0]), int(iris[1]), int(iris[2])
        # Pupil — smaller, darker circle inside iris
        roi = gray[max(0,iy-ir):iy+ir, max(0,ix-ir):ix+ir]
        if roi.size == 0:
            return {"status": "no_pupil", "reason": "pupil ROI empty"}
        # Threshold for dark pupil
        _, thresh = cv2.threshold(roi, 50, 255, cv2.THRESH_BINARY_INV)
        # Find pupil as darkest circle
        pc = cv2.HoughCircles(thresh, cv2.HOUGH_GRADIENT, 1, 10, param1=30, param2=15, minRadius=int(ir*0.15), maxRadius=int(ir*0.5))
        if pc is not None:
            pc = np.uint16(np.around(pc[0][0]))
            px, py, pr = int(pc[0]) + max(0,ix-ir), int(pc[1]) + max(0,iy-ir), int(pc[2])
        else:
            # Fallback: pupil at iris center, 0.35*iris radius
            px, py, pr = ix, iy, int(ir*0.35)
        # Simple occlusion mask: assume eyelids cover top 15% if needed
        mask = np.zeros((h,w), dtype=np.uint8)
        cv2.circle(mask, (ix,iy), ir, 255, -1)
        cv2.circle(mask, (px,py), pr, 0, -1)
        return {
            "status": "ok",
            "iris": (ix, iy, ir),
            "pupil": (px, py, pr),
            "mask": mask,
            "quality": 0.6,
        }
    except Exception as e:
        return {"status": "error", "reason": str(e)[:80]}
