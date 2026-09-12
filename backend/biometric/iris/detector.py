"""Eye detection for iris pipeline — uses MediaPipe FaceLandmarker eye landmarks."""

from __future__ import annotations
import cv2
import numpy as np
from typing import Dict, Any, Optional

def detect_eyes(bgr: np.ndarray) -> Dict[str, Any]:
    """Detect left and right eye regions via MediaPipe."""
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_py
        from mediapipe.tasks.python import vision
        import os
        task = os.path.join(os.path.dirname(__file__), "../../../pipeline/vendor/models/face_landmarker.task")
        task = os.path.abspath(task)
        if not os.path.exists(task):
            return {"status": "error", "reason": "face_landmarker not found"}
        landmarker = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=mp_py.BaseOptions(model_asset_path=task),
                running_mode=vision.RunningMode.IMAGE,
                num_faces=1,
            )
        )
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        res = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        landmarker.close()
        if not res.face_landmarks:
            return {"status": "no_face", "reason": "no face/eye found"}
        lm = res.face_landmarks[0]
        h, w = bgr.shape[:2]
        # Eye landmarks: left 33, right 263, use bbox around eye
        left_x = int(lm[33].x * w); left_y = int(lm[33].y * h)
        right_x = int(lm[263].x * w); right_y = int(lm[263].y * h)
        # Estimate eye crops 80x80 around each eye
        def crop_eye(cx, cy):
            x0, y0 = max(0, cx-40), max(0, cy-30)
            x1, y1 = min(w, cx+40), min(h, cy+30)
            return bgr[y0:y1, x0:x1], (x0, y0, x1, y1)
        left_crop, left_box = crop_eye(left_x, left_y)
        right_crop, right_box = crop_eye(right_x, right_y)
        return {
            "status": "ok",
            "left_eye": {"crop": left_crop, "bbox": left_box, "center": (left_x, left_y)},
            "right_eye": {"crop": right_crop, "bbox": right_box, "center": (right_x, right_y)},
        }
    except Exception as e:
        return {"status": "error", "reason": str(e)[:80]}
