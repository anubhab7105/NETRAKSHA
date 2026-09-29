"""Rubber-sheet (polar) normalization of segmented iris."""

from __future__ import annotations
import cv2
import numpy as np
from typing import Dict, Any

def normalize_iris(eye_bgr: np.ndarray, pupil: tuple, iris: tuple, mask=None) -> Dict[str, Any]:
    """Unwrap iris ring to polar representation (64x512)."""
    try:
        px, py, pr = pupil
        ix, iy, ir = iris
        h, w = eye_bgr.shape[:2]

        R, T = 64, 512
        normalized = np.zeros((R, T, 3), dtype=np.uint8)
        norm_mask = np.zeros((R, T), dtype=np.uint8)
        for r in range(R):

            rad = pr + (r / R) * (ir - pr)
            for t in range(T):
                theta = 2 * np.pi * t / T
                x = int(ix + rad * np.cos(theta))
                y = int(iy + rad * np.sin(theta))
                if 0 <= x < w and 0 <= y < h:
                    normalized[r, t] = eye_bgr[y, x]

                    if mask is not None:
                        if 0 <= y < mask.shape[0] and 0 <= x < mask.shape[1]:
                            norm_mask[r, t] = mask[y, x]
                        else:
                            norm_mask[r, t] = 0
                    else:
                        norm_mask[r, t] = 255
        return {"status": "ok", "normalized": normalized, "mask": norm_mask}
    except Exception as e:
        return {"status": "error", "reason": str(e)[:80]}
