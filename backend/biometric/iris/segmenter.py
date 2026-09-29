
from __future__ import annotations
import cv2
import numpy as np
from typing import Dict, Any

def segment_iris(eye_bgr: np.ndarray) -> Dict[str, Any]:
    try:
        gray = cv2.cvtColor(eye_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.medianBlur(gray, 5)
        h, w = gray.shape[:2]

        circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, 1, 20, param1=50, param2=30, minRadius=int(min(h,w)*0.15), maxRadius=int(min(h,w)*0.45))
        method = "hough"
        if circles is None:
            circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, 1, 15, param1=40, param2=18, minRadius=int(min(h,w)*0.10), maxRadius=int(min(h,w)*0.50))
        if circles is None:



            ix, iy, ir = w // 2, h // 2, int(min(h, w) * 0.28)
            method = "geometric_fallback"
        else:
            circles = np.uint16(np.around(circles))
            iris = circles[0][0]
            ix, iy, ir = int(iris[0]), int(iris[1]), int(iris[2])

        roi = gray[max(0,iy-ir):iy+ir, max(0,ix-ir):ix+ir]
        if roi.size == 0:
            return {"status": "no_pupil", "reason": "pupil ROI empty"}

        _, thresh = cv2.threshold(roi, 50, 255, cv2.THRESH_BINARY_INV)

        pc = cv2.HoughCircles(thresh, cv2.HOUGH_GRADIENT, 1, 10, param1=30, param2=15, minRadius=int(ir*0.15), maxRadius=int(ir*0.5))
        if pc is not None:
            pc = np.uint16(np.around(pc[0][0]))
            px, py, pr = int(pc[0]) + max(0,ix-ir), int(pc[1]) + max(0,iy-ir), int(pc[2])
        else:

            px, py, pr = ix, iy, int(ir*0.35)

        mask = np.zeros((h,w), dtype=np.uint8)
        cv2.circle(mask, (ix,iy), ir, 255, -1)
        cv2.circle(mask, (px,py), pr, 0, -1)
        return {
            "status": "ok",
            "iris": (ix, iy, ir),
            "pupil": (px, py, pr),
            "mask": mask,
            "quality": 0.6,
            "method": method,
        }
    except Exception as e:
        return {"status": "error", "reason": str(e)[:80]}
