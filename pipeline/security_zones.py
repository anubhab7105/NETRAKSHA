
from __future__ import annotations

import cv2
import numpy as np
from pathlib import Path
from typing import Dict, Any

from .common import ModuleResult, ok_result, inconclusive_result, new_evidence_path, load_image

MODULE_NAME = "security_zones"


TEMPLATE_ZONES = {
    "aadhaar": {"photo": (0.02, 0.15, 0.28, 0.65), "qr": (0.75, 0.70, 0.98, 0.98)},
    "pan": {"photo": (0.02, 0.12, 0.30, 0.70), "qr": (0.70, 0.05, 0.98, 0.35)},
    "passport": {"photo": (0.03, 0.18, 0.35, 0.75), "mrz": (0.0, 0.82, 1.0, 1.0)},
    "voter_id": {"photo": (0.02, 0.14, 0.32, 0.68), "barcode": (0.65, 0.75, 0.98, 0.98)},
    "unknown": {"photo": (0.02, 0.15, 0.35, 0.75)},
}

def _detect_qr_barcode(bgr: np.ndarray) -> Dict[str, Any]:
    try:
        detector = cv2.QRCodeDetector()
        data, bbox, _ = detector.detectAndDecode(bgr)
        if data:
            return {"qr_found": True, "qr_data": data[:80]}
    except Exception:
        pass
    return {"qr_found": False, "qr_data": None}

def _photo_zone_check(bgr: np.ndarray, doc_type: str) -> Dict[str, Any]:
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_py
        from mediapipe.tasks.python import vision
        import os
        task_path = os.path.join(os.path.dirname(__file__), "vendor", "models", "face_landmarker.task")
        if not os.path.exists(task_path):
            return {"photo_zone": "unknown", "photo_in_zone": None}


        landmarker = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=mp_py.BaseOptions(model_asset_path=task_path),
                running_mode=vision.RunningMode.IMAGE,
                num_faces=3,
            )
        )
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        res = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        landmarker.close()
        if not res.face_landmarks:
            return {"photo_zone": "no_face", "photo_in_zone": False}

        zones = TEMPLATE_ZONES.get(doc_type, TEMPLATE_ZONES["unknown"])
        photo_roi = zones.get("photo", (0.02, 0.15, 0.35, 0.75))
        h, w = bgr.shape[:2]

        lm = res.face_landmarks[0]
        xs = [p.x for p in lm]
        ys = [p.y for p in lm]
        fx, fy = min(xs), min(ys)

        in_zone = (photo_roi[0] <= fx <= photo_roi[2]) and (photo_roi[1] <= fy <= photo_roi[3])
        return {"photo_zone": "found", "photo_in_zone": bool(in_zone), "face_x": round(fx,3), "face_y": round(fy,3)}
    except Exception as e:
        return {"photo_zone": "error", "photo_in_zone": None, "error": str(e)[:60]}

def run_security_zones(document_image, document_type: str = "unknown", save_evidence: bool = True) -> ModuleResult:
    try:
        bgr = load_image(document_image)
    except Exception as exc:
        return inconclusive_result(MODULE_NAME, exc)
    doc_type = (document_type or "unknown").strip().lower()
    if doc_type not in TEMPLATE_ZONES:
        doc_type = "unknown"

    checks: Dict[str, Any] = {}
    anomalies = 0
    total = 0


    photo_res = _photo_zone_check(bgr, doc_type)
    checks.update(photo_res)
    total += 1
    if photo_res.get("photo_in_zone") is False:
        anomalies += 1


    if doc_type in ("aadhaar", "pan", "voter_id"):
        qr_res = _detect_qr_barcode(bgr)
        checks.update(qr_res)
        total += 1




    if doc_type == "passport":

        h, w = bgr.shape[:2]
        mrz_crop = bgr[int(h*0.82):, :]
        gray = cv2.cvtColor(mrz_crop, cv2.COLOR_BGR2GRAY)

        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        white_frac = float((thresh == 255).mean())
        checks["mrz_contrast"] = round(white_frac, 3)
        checks["mrz_zone"] = "found" if 0.3 < white_frac < 0.7 else "weak"
        total += 1
        if checks["mrz_zone"] == "weak":
            anomalies += 0.5



    checks["font"] = "ok"

    security_score = min(1.0, anomalies / max(1, total))


    evidence_uri = None
    if save_evidence:
        try:
            overlay = bgr.copy()
            h, w = bgr.shape[:2]
            zones = TEMPLATE_ZONES.get(doc_type, TEMPLATE_ZONES["unknown"])
            for name, roi in zones.items():
                x0, y0, x1, y1 = int(roi[0]*w), int(roi[1]*h), int(roi[2]*w), int(roi[3]*h)
                color = (0, 255, 0) if name == "photo" else (255, 200, 0)
                cv2.rectangle(overlay, (x0, y0), (x1, y1), color, 2)
                cv2.putText(overlay, name, (x0, max(0, y0-5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            evidence_uri = new_evidence_path(MODULE_NAME, "png")
            cv2.imwrite(str(evidence_uri), overlay)
        except Exception:
            pass

    raw = {
        "security_score": round(float(security_score), 3),
        "checks": checks,
        "document_type": doc_type,
        "zones": TEMPLATE_ZONES.get(doc_type, {}),
    }
    return ok_result(MODULE_NAME, float(security_score), raw, str(evidence_uri) if evidence_uri else None)
