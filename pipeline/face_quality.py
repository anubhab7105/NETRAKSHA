"""Face-image quality gates — run BEFORE biometric matching.

Poor captures (blur, bad light, tiny/off-angle faces, extra people in frame)
are the top cause of false rejections and wrong 1:1 verdicts. Every check in
this module is a cheap OpenCV/numpy measurement plus the detector output the
caller already has — no extra model downloads, no network, never raises.

Two stages (orchestrated by ``face_match.run_face_match``):

1. :func:`assess_capture` — whole-image hygiene, no face detection needed
   (resolution floor, lens-covered / flash-blown exposure).
2. :func:`assess_face` — per-face usability on the detector's chosen face
   crop (blur, brightness, face size, head pose from landmarks, face count,
   occlusion advisory).

Inputs smaller than :data:`REFERENCE_MAX_DIM` are pre-cropped reference
thumbnails (e.g. 96px registry photos), not camera captures — hard gates are
skipped for those (``reference_mode``) so enrolled reference data keeps
verifying; only face presence is required.

Reason codes are stable strings (see :data:`RECAPTURE_GUIDANCE`) so the API
and UI can render "please recapture" prompts without parsing free text.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Thresholds (calibrated on repo samples: good live crop lap≈158, doc face
# crop lap≈743, V≈139-152; heavy Gaussian blur collapses lap below ~15).
# Overridable via environment for site-specific cameras — no code change.
# ---------------------------------------------------------------------------

#: Below this full-image mean V, the lens is covered / room is dark.
CAPTURE_DARK_MEAN_V = _env_float("FACE_Q_CAPTURE_DARK_V", 20.0)
#: Above this full-image mean V, the frame is flash-blown.
CAPTURE_BRIGHT_MEAN_V = _env_float("FACE_Q_CAPTURE_BRIGHT_V", 240.0)
#: Captures with a smaller min-dimension than this are reference thumbnails.
REFERENCE_MAX_DIM = int(_env_float("FACE_Q_REFERENCE_MAX_DIM", 240))
#: Minimum face-crop sharpness (Laplacian variance, 200px-normalised).
BLUR_MIN = _env_float("FACE_Q_BLUR_MIN", 45.0)
#: Face-crop brightness band (HSV value-channel mean).
BRIGHT_MIN = _env_float("FACE_Q_BRIGHT_MIN", 55.0)
BRIGHT_MAX = _env_float("FACE_Q_BRIGHT_MAX", 215.0)
#: Face-crop contrast floor (V-channel std — flat grey = covered sensor).
CONTRAST_MIN = _env_float("FACE_Q_CONTRAST_MIN", 12.0)
#: Smallest usable face bounding box (min side, px) in full-capture mode.
FACE_MIN_PX = _env_float("FACE_Q_FACE_MIN_PX", 90.0)
#: Smallest usable face as a fraction of frame area in full-capture mode.
FACE_MIN_FRAC = _env_float("FACE_Q_FACE_MIN_FRAC", 0.01)
#: |yaw proxy| above this means a side-angle capture (see yaw_proxy_from_kps).
YAW_MAX = _env_float("FACE_Q_YAW_MAX", 0.30)
#: Occlusion advisory only (beards trigger naive detectors): lower-face edge
#: density ratio below this raises `occlusion_suspected` as a WARNING.
OCCLUSION_EDGE_RATIO = _env_float("FACE_Q_OCCLUSION_EDGE_RATIO", 0.40)

#: Hard-gate failures. `occlusion_suspected` is deliberately NOT here — it is
#: advisory (beards/scarves), while the rest are measurement failures.
HARD_FAILURES = frozenset({
    "unreadable", "image_too_small", "too_dark", "too_bright",
    "no_face", "multi_face", "face_too_small", "blurry",
    "dark_face", "bright_face", "flat_contrast", "side_angle",
})

#: Officer-facing recapture instructions per reason code.
RECAPTURE_GUIDANCE: Dict[str, str] = {
    "unreadable": "Image could not be read — recapture the {role}.",
    "image_too_small": "Capture resolution is too low — move closer / check the camera and recapture the {role}.",
    "too_dark": "Frame is nearly black — turn on lights and recapture the {role}.",
    "too_bright": "Frame is washed out by glare/flash — reduce light and recapture the {role}.",
    "no_face": "No face was found — face the camera straight on in good light and recapture the {role}.",
    "multi_face": "More than one face is in frame — only the traveller should face the camera; recapture the {role}.",
    "face_too_small": "Face is too small / far away — move closer to the camera and recapture the {role}.",
    "blurry": "Image is too blurry — hold still, tap to focus, and recapture the {role}.",
    "dark_face": "Face is too dark — add frontal light (no backlight) and recapture the {role}.",
    "bright_face": "Face is overexposed — step out of direct light and recapture the {role}.",
    "flat_contrast": "Face region is unnaturally flat — check the lens is clean and recapture the {role}.",
    "side_angle": "Face is turned sideways — look directly at the camera and recapture the {role}.",
    "occlusion_suspected": "Something may be covering the lower face (mask/scarf/hand) — remove it and recapture the {role}.",
}

_ROLE_LABEL = {"live": "live capture", "document": "document photo"}


@dataclass
class QualityReport:
    """Outcome of the quality gates for one input image."""

    role: str  # "live" | "document"
    passed: bool = True
    reference_mode: bool = False  # tiny pre-cropped reference thumbnail
    failed: List[str] = field(default_factory=list)  # hard-gate reason codes
    warnings: List[str] = field(default_factory=list)  # advisory codes
    metrics: Dict[str, Any] = field(default_factory=dict)

    def recapture_reasons(self) -> List[str]:
        label = _ROLE_LABEL.get(self.role, self.role)
        return [RECAPTURE_GUIDANCE[c].format(role=label) for c in self.failed if c in RECAPTURE_GUIDANCE]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "gate": "passed" if self.passed else "failed",
            "reference_mode": self.reference_mode,
            "failed_checks": list(self.failed),
            "warnings": list(self.warnings),
            "metrics": dict(self.metrics),
            "recapture_reasons": self.recapture_reasons(),
        }


# ---------------------------------------------------------------------------
# Low-level measurements (pure functions — unit-testable without a detector)
# ---------------------------------------------------------------------------

def laplacian_sharpness(gray: Any, norm_width: int = 200) -> float:
    """Variance of Laplacian on a width-normalised grayscale crop.

    Normalising first keeps the threshold meaningful across resolutions:
    a sharp 96px thumbnail and a sharp 1024px frame score comparably.
    """
    import cv2

    g = gray
    h, w = g.shape[:2]
    if w != norm_width:
        g = cv2.resize(g, (norm_width, max(1, int(h * norm_width / max(1, w)))))
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def brightness_stats(bgr: Any) -> Tuple[float, float, float, float]:
    """Return (mean_V, std_V, dark_frac, bright_frac) for a BGR image."""
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    v = hsv[:, :, 2].astype(np.float32)
    return (
        float(v.mean()),
        float(v.std()),
        float((v < 25).mean()),
        float((v > 230).mean()),
    )


def yaw_proxy_from_kps(kps: Any) -> Optional[float]:
    """Estimate head yaw from 5-point landmarks, independent of image size.

    kps order (InsightFace): left_eye, right_eye, nose, mouth_l, mouth_r.
    Returns (nose.x − eye_mid.x) / eye_dist — ≈0 frontal, ±0.4+ in profile.
    Returns None when landmarks are missing/unusable.
    """
    try:
        import numpy as np

        pts = np.asarray(kps, dtype=float).reshape(-1, 2)
        if pts.shape[0] < 3:
            return None
        left, right, nose = pts[0], pts[1], pts[2]
        eye_dist = float(np.linalg.norm(right - left))
        if eye_dist < 1e-6:
            return None
        mid_x = (left[0] + right[0]) / 2.0
        return float((nose[0] - mid_x) / eye_dist)
    except Exception:
        return None


def occlusion_hint(face_crop_bgr: Any) -> Tuple[bool, Dict[str, float]]:
    """Advisory mask/scarf/hand check on a face crop.

    A covering over the mouth region wipes out edges there while the eyes
    stay textured, so a collapsed lower/upper Canny-edge-density ratio is
    suspicious. Beards fool naive versions of this test, hence ADVISORY
    ONLY — never a hard gate (see module docstring).
    """
    import cv2
    import numpy as np

    try:
        gray = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2GRAY)
        h, _ = gray.shape[:2]
        if h < 30:
            return False, {}
        upper = gray[: h // 2, :]
        lower = gray[h // 2 :, :]
        eu = cv2.Canny(upper, 60, 140)
        el = cv2.Canny(lower, 60, 140)
        du = float(eu.mean()) / 255.0 + 1e-6
        dl = float(el.mean()) / 255.0
        ratio = dl / du
        lower_std = float(lower.std())
        suspected = bool(ratio < OCCLUSION_EDGE_RATIO and lower_std < 22.0)
        return suspected, {"edge_ratio_lower_upper": round(ratio, 3), "lower_std": round(lower_std, 1)}
    except Exception:
        return False, {}


# ---------------------------------------------------------------------------
# Gate stages
# ---------------------------------------------------------------------------

def assess_capture(image_bgr: Any, role: str) -> QualityReport:
    """Stage 1 — whole-image hygiene (no face detection required)."""
    rep = QualityReport(role=role)
    try:
        h, w = image_bgr.shape[:2]
    except Exception:
        rep.passed = False
        rep.failed.append("unreadable")
        return rep
    rep.metrics.update({"width": int(w), "height": int(h)})
    if min(h, w) < REFERENCE_MAX_DIM:
        rep.reference_mode = True
        rep.metrics["mode"] = "reference_thumbnail — hard gates skipped, face presence only"
        return rep
    try:
        mean_v, _, dark_frac, bright_frac = brightness_stats(image_bgr)
    except Exception:
        rep.passed = False
        rep.failed.append("unreadable")
        return rep
    rep.metrics.update({
        "mean_v": round(mean_v, 1),
        "dark_frac": round(dark_frac, 3),
        "bright_frac": round(bright_frac, 3),
    })
    if mean_v < CAPTURE_DARK_MEAN_V or dark_frac > 0.85:
        rep.passed = False
        rep.failed.append("too_dark")
    elif mean_v > CAPTURE_BRIGHT_MEAN_V or bright_frac > 0.85:
        rep.passed = False
        rep.failed.append("too_bright")
    return rep


def assess_face(
    image_bgr: Any,
    face: Any,
    face_count: int,
    role: str,
    face_crop_bgr: Any = None,
) -> QualityReport:
    """Stage 2 — usability of the detector's chosen face.

    ``face`` is the InsightFace face object (needs ``bbox``; ``kps`` used
    for pose when present). ``face_crop_bgr`` may be supplied to skip
    re-cropping (tests); otherwise it is cropped with padding here.
    """
    rep = QualityReport(role=role)
    try:
        ih, iw = image_bgr.shape[:2]
    except Exception:
        rep.passed = False
        rep.failed.append("unreadable")
        return rep

    # --- face count gate (live captures must isolate the traveller) ---
    rep.metrics["faces_detected"] = int(face_count or 0)
    if (face_count or 0) == 0:
        rep.passed = False
        rep.failed.append("no_face")
        return rep
    if role == "live" and (face_count or 0) > 1:
        rep.passed = False
        rep.failed.append("multi_face")
    elif (face_count or 0) > 1:
        rep.warnings.append("multi_face")

    if face is None:
        rep.passed = False
        if "no_face" not in rep.failed:
            rep.failed.append("no_face")
        return rep

    # --- face size gate ---
    try:
        import numpy as np

        bbox = np.asarray(getattr(face, "bbox"), dtype=float).reshape(-1)
        x1, y1, x2, y2 = (max(0.0, float(bbox[0])), max(0.0, float(bbox[1])),
                          min(float(iw), float(bbox[2])), min(float(ih), float(bbox[3])))
        bw, bh = max(0.0, x2 - x1), max(0.0, y2 - y1)
        frac = (bw * bh) / max(1.0, float(iw * ih))
    except Exception:
        rep.passed = False
        rep.failed.append("no_face")
        return rep
    rep.metrics.update({
        "face_w": round(bw, 1), "face_h": round(bh, 1),
        "face_frac": round(frac, 4),
    })
    if min(bw, bh) < FACE_MIN_PX or frac < FACE_MIN_FRAC:
        rep.passed = False
        rep.failed.append("face_too_small")
        return rep  # too few pixels for any downstream measurement to mean anything

    # --- face-crop sharpness / light gates ---
    try:
        import cv2

        crop = face_crop_bgr
        if crop is None:
            pad = 0.25
            px1, py1 = max(0, int(x1 - bw * pad)), max(0, int(y1 - bh * pad))
            px2, py2 = min(iw, int(x2 + bw * pad)), min(ih, int(y2 + bh * pad))
            crop = image_bgr[py1:py2, px1:px2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        sharp = laplacian_sharpness(gray)
        mean_v, std_v, _, _ = brightness_stats(crop)
    except Exception:
        rep.passed = False
        rep.failed.append("unreadable")
        return rep
    rep.metrics.update({
        "sharpness": round(sharp, 1),
        "face_mean_v": round(mean_v, 1),
        "face_contrast": round(std_v, 1),
    })
    if sharp < BLUR_MIN:
        rep.passed = False
        rep.failed.append("blurry")
    if mean_v < BRIGHT_MIN:
        rep.passed = False
        rep.failed.append("dark_face")
    elif mean_v > BRIGHT_MAX:
        rep.passed = False
        rep.failed.append("bright_face")
    if std_v < CONTRAST_MIN and "dark_face" not in rep.failed and "bright_face" not in rep.failed:
        rep.passed = False
        rep.failed.append("flat_contrast")

    # --- head-pose gate (side angle destroys 1:1 similarity) ---
    yaw = yaw_proxy_from_kps(getattr(face, "kps", None))
    if yaw is not None:
        rep.metrics["yaw_proxy"] = round(yaw, 3)
        if abs(yaw) > YAW_MAX:
            rep.passed = False
            rep.failed.append("side_angle")
    else:
        pose = getattr(face, "pose", None)
        try:
            import numpy as np

            p = np.asarray(pose, dtype=float).reshape(-1) if pose is not None else None
            if p is not None and p.size >= 2 and abs(float(p[1])) > 25.0:
                rep.passed = False
                rep.failed.append("side_angle")
            rep.metrics["yaw_deg"] = round(float(p[1]), 1) if p is not None and p.size >= 2 else None
        except Exception:
            pass

    # --- occlusion advisory (never a hard gate — see occlusion_hint) ---
    try:
        suspected,ometrics = occlusion_hint(crop)
        rep.metrics.update(ometrics)
        if suspected:
            rep.warnings.append("occlusion_suspected")
    except Exception:
        pass

    rep.passed = not any(c in HARD_FAILURES for c in rep.failed)
    return rep


def combine_reports(*reports: QualityReport) -> Dict[str, Any]:
    """Merge per-input reports into the raw_output quality block."""
    failed_targets = sorted({r.role for r in reports if not r.passed})
    reasons: List[str] = []
    for r in reports:
        reasons.extend(r.recapture_reasons())
    return {
        "gate": "passed" if not failed_targets else "failed",
        "failed_targets": failed_targets,
        "recapture_requested": bool(failed_targets),
        "recapture_target": failed_targets[0] if len(failed_targets) == 1 else ("both" if failed_targets else None),
        "recapture_reasons": reasons,
        "inputs": {r.role: r.to_dict() for r in reports},
    }
