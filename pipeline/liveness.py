"""Module 5 — Liveness detection.

Approach (Techspec.md §3): multi-signal liveness across a short webcam frame
burst, using mediapipe face-mesh landmarks. Instead of trusting a single signal
we fuse three independent cues:

  1. BLINK (Eye-Aspect-Ratio) — an adaptive per-burst EAR baseline replaces the
     old hard-coded threshold, then validated blink runs are counted.
  2. MOTION — mean inter-frame landmark displacement normalised by face width.
     A real person (even when asked to hold still) produces micro-movements; a
     printed photo or a frozen video frame produces ~zero displacement.
  3. SCREEN ARTIFACTS — FFT analysis of the face crop for moire / pixel-grid
     periodic energy, which is a strong tell for photo/video replay from a
     monitor (any display attack).

Decision logic (status == "ok"):
  * insufficient face coverage                          -> inconclusive
  * no motion AND no blink                              -> NOT live (still image)
  * strong screen artifacts                             -> NOT live (display replay)
  * otherwise score = blink/motion signal * 0.55
                       + clean-signal * 0.25
                       + face coverage * 0.20
                     live = score >= 0.45

Contract flags (Techspec.md §3, for the Risk Engine owner):
  * ``live: bool`` is unambiguous whenever status == "ok" — never None except
    when the ENTIRE module is inconclusive. A failed liveness check is one of
    the two conditions that forces a case to at least Yellow.
  * We never return live=None on an "ok" result.

Never raises: any internal failure degrades to status="inconclusive", score=None.
"""

from __future__ import annotations

import os
import pathlib
from typing import List, Optional, Union

import numpy as np

from .common import (
    ModuleResult,
    inconclusive_result,
    load_image,
    ok_result,
)

MODULE_NAME = "liveness"

# Active challenge types — randomized per session
CHALLENGE_TYPES = ["blink", "head_turn", "mouth_open"]
# Minimum yaw (from face_quality yaw_proxy) for head_turn
HEAD_YAW_THRESHOLD = 0.30  # ~25 degrees
# Minimum mouth opening (normalized) for mouth_open
MOUTH_OPEN_THRESHOLD = 0.04

# minimum number of frames required to be considered a real burst
MIN_BURST_FRAMES = 3
# minimum fraction of frames with a detected face before we trust analysis
MIN_COVERAGE = 0.5
# mean normalised landmark displacement below this => still / frozen sequence
STATIC_MOTION = 0.002
# reference motion used to normalise the motion signal (0 -> 1)
MOTION_REF = 0.015
# screen-artifact score above this => display replay suspected
SCREEN_SPOOF = 0.60
# final liveness score threshold for live=True
LIVE_THRESHOLD = 0.45
# minimum EAR drop (absolute) for a blink event to count (noise rejection)
BLINK_DEPTH = 0.01

# mediapipe FaceLandmarker task model (downloaded; see pipeline/vendor/models)
_FACELANDMARKER_TASK = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "vendor",
    "models",
    "face_landmarker.task",
)

# Standard 468-point eye landmark indices for the mediapipe face-mesh model.
_LEFT_EYE = [33, 160, 158, 133, 153, 144]
_RIGHT_EYE = [362, 385, 387, 263, 373, 380]


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _ear(landmarks, indices) -> Optional[float]:
    """Compute eye aspect ratio from a mediapipe landmark list for one eye."""
    try:
        pts = [landmarks[i] for i in indices]
    except (IndexError, TypeError):
        return None

    def _vec(p):
        return np.array([p.x, p.y])

    a, b, c, d, e, f = (_vec(pts[0]), _vec(pts[1]), _vec(pts[2]),
                        _vec(pts[3]), _vec(pts[4]), _vec(pts[5]))
    v1 = np.linalg.norm(b - f)
    v2 = np.linalg.norm(c - e)
    v3 = np.linalg.norm(a - d)
    if v3 < 1e-6:
        return None
    return float((v1 + v2) / (2.0 * v3))


def _face_mesh():
    """Create a mediapipe FaceLandmarker running in IMAGE mode.

    mediapipe >= 1.0 exposes the `tasks` API only (the legacy `mp.solutions`
    was removed), so we use FaceLandmarker with a downloaded .task model.
    """
    from mediapipe.tasks import python as mp_py
    from mediapipe.tasks.python import vision

    if not os.path.exists(_FACELANDMARKER_TASK):
        raise FileNotFoundError(
            f"mediapipe FaceLandmarker model not found: {_FACELANDMARKER_TASK}"
        )
    return vision.FaceLandmarker.create_from_options(
        vision.FaceLandmarkerOptions(
            base_options=mp_py.BaseOptions(model_asset_path=_FACELANDMARKER_TASK),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=1,
        )
    )


def _collect_frames(burst_input) -> List[np.ndarray]:
    """Normalise a frame burst into a list of BGR ndarrays."""
    if isinstance(burst_input, (str, pathlib.Path, os.PathLike)):
        p = pathlib.Path(burst_input)
        if p.suffix.lower() in {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}:
            return _frames_from_video(p)
        # single image path -> single frame (low burst)
        return [load_image(p)]

    if isinstance(burst_input, (list, tuple)) and len(burst_input) > 0:
        # if it's a list of frames/paths
        if isinstance(burst_input[0], (str, pathlib.Path, os.PathLike)):
            return [load_image(x) for x in burst_input]
        # list of ndarrays
        if isinstance(burst_input[0], np.ndarray):
            return [x.astype(np.uint8) for x in burst_input]
        # list of PIL
        return [load_image(x) for x in burst_input]

    # single ndarray / single PIL image
    return [load_image(burst_input)]


def _frames_from_video(path: pathlib.Path, max_frames: int = 12) -> List[np.ndarray]:
    import cv2

    cap = cv2.VideoCapture(str(path))
    frames = []
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or max_frames
        step = max(1, total // max_frames)
        i = 0
        while len(frames) < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            if i % step == 0:
                frames.append(frame)
            i += 1
    finally:
        cap.release()
    if not frames:
        raise ValueError(f"could not read frames from video: {path}")
    return frames


# ---------------------------------------------------------------------------
# Per-frame feature extraction
# ---------------------------------------------------------------------------

def _extract_frame_features(landmarker, mp, frame: np.ndarray):
    """Return (ear, landmarks_xy, bbox) for one frame, or None if no face."""
    rgb = frame[:, :, ::-1] if frame.ndim == 3 and frame.shape[2] == 3 else frame
    if rgb.dtype != np.uint8:
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    results = landmarker.detect(
        mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    )
    if not results or not results.face_landmarks:
        return None

    lm = results.face_landmarks[0]
    left = _ear(lm, _LEFT_EYE)
    right = _ear(lm, _RIGHT_EYE)
    if left is None or right is None:
        return None

    pts = np.array([[p.x, p.y] for p in lm], dtype=np.float64)
    min_x, min_y = float(pts[:, 0].min()), float(pts[:, 1].min())
    max_x, max_y = float(pts[:, 0].max()), float(pts[:, 1].max())
    return (float((left + right) / 2.0), pts, (min_x, min_y, max_x, max_y))


def _screen_artifact_score(frame: np.ndarray, bbox) -> float:
    """Estimate display-replay likelihood from moire/pixel-grid energy.

    A real camera capturing a monitor shows strong periodic high-frequency
    energy (the screen's pixel grid / refresh pattern); a direct webcam feed
    of a face does not. Returns 0..1 scale (higher = more screen-like).
    """
    try:
        import cv2

        min_x, min_y, max_x, max_y = bbox
        h, w = frame.shape[:2]
        x0 = max(0, int(min_x * w))
        y0 = max(0, int(min_y * h))
        x1 = min(w, int(max_x * w))
        y1 = min(h, int(max_y * h))
        if x1 - x0 < 16 or y1 - y0 < 16:
            return 0.0

        crop = frame[y0:y1, x0:x1]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (128, 128), interpolation=cv2.INTER_AREA)
        gray = gray.astype(np.float64)

        window = np.hanning(128)
        window_2d = np.outer(window, window)
        gray = (gray - gray.mean()) * window_2d

        spectrum = np.abs(np.fft.fftshift(np.fft.fft2(gray)))
        # log magnitude compresses dynamic range -> measurable peaks stand out
        mag = np.log1p(spectrum)

        cy, cx = 64, 64
        ys, xs = np.mgrid[0:128, 0:128]
        r = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2) / 64.0  # normalized 0..~1.4
        total_mask = r >= 3.0 / 64.0  # exclude DC core

        # high-frequency fraction (ring power above r=0.35 vs above r>=3px)
        high_mask = (r >= 0.35) & (r <= 1.0)
        total_energy = float(mag[total_mask].sum()) + 1e-9
        high_energy = float(mag[high_mask].sum())
        high_fraction = high_energy / total_energy

        # grid peakiness: how spiky the mid-to-high band is
        band = (r >= 0.20) & (r <= 0.80)
        band_vals = mag[band]
        if band_vals.size == 0:
            peakiness = 1.0
        else:
            peakiness = float(band_vals.max()) / (float(band_vals.mean()) + 1e-9)

        hf_signal = np.clip((high_fraction - 0.10) / 0.20, 0.0, 1.0)
        pk_signal = np.clip((peakiness - 2.0) / 5.0, 0.0, 1.0)
        return float(0.5 * hf_signal + 0.5 * pk_signal)
    except Exception:  # noqa: BLE001  (feature is best-effort)
        return 0.0


# ---------------------------------------------------------------------------
# Burst analysis
# ---------------------------------------------------------------------------

def _analyse_burst(frames: List[np.ndarray]) -> dict:
    """Extract EAR, motion and screen-artifact signals across the burst."""
    import mediapipe as mp

    landmarker = _face_mesh()
    try:
        features = []  # (ear, pts, bbox) or None per frame
        ear_series = []
        for frame in frames:
            feat = _extract_frame_features(landmarker, mp, frame)
            features.append(feat)
            ear_series.append(feat[0] if feat else None)

        n_frames = len(frames)
        valid_idx = [i for i, f in enumerate(features) if f is not None]
        n_landmarks = len(valid_idx)
        coverage = (n_landmarks / n_frames) if n_frames else 0.0

        stats = {
            "n_frames": n_frames,
            "n_landmarks": n_landmarks,
            "coverage": round(float(coverage), 4),
            "ear_mean": None,
            "ear_min": None,
            "ear_max": None,
            "ear_swing": None,
            "eye_closed_threshold": None,
            "blinks": 0,
            "motion_score": None,
            "screen_artifact_score": None,
        }

        if n_landmarks == 0:
            return stats

        # --- adaptive blink detection ---
        arr = np.asarray([ear_series[i] for i in valid_idx], dtype=np.float64)
        baseline = float(np.percentile(arr, 75))  # open-eye reference
        # 0.72 * baseline reproduces the old fixed 0.21 threshold for a typical
        # open-eye EAR of ~0.29 WITHOUT hard-coding it, so still adapts per face.
        closed_thr = min(0.27, max(0.14, baseline * 0.72))

        blinks = 0
        i = 0
        while i < len(arr):
            if arr[i] < closed_thr:
                j = i
                run_min = arr[i]
                while j < len(arr) and arr[j] < closed_thr:
                    run_min = min(run_min, arr[j])
                    j += 1
                # a genuine blink dips meaningfully below the open-eye baseline
                rel_drop = baseline - run_min
                if rel_drop >= baseline * 0.25:
                    blinks += 1
                i = j
            else:
                i += 1

        # --- motion (inter-frame landmark displacement / face width) ---
        displacements = []
        prev = features[valid_idx[0]]
        for idx in valid_idx[1:]:
            cur = features[idx]
            face_w = prev[2][2] - prev[2][0]
            if face_w > 1e-6:
                disp = float(np.mean(np.linalg.norm(cur[1] - prev[1], axis=1)))
                displacements.append(disp / face_w)
            prev = cur
        motion_score = float(np.mean(displacements)) if displacements else 0.0

        # --- screen artifact (best-effort, over face frames) ---
        screen_scores = [
            _screen_artifact_score(frames[idx], features[idx][2])
            for idx in valid_idx
        ]
        screen_score = float(np.mean(screen_scores)) if screen_scores else 0.0

        stats.update({
            "ear_mean": round(float(np.mean(arr)), 4),
            "ear_min": round(float(np.min(arr)), 4),
            "ear_max": round(float(np.max(arr)), 4),
            "ear_swing": round(float(np.max(arr) - np.min(arr)), 4),
            "eye_closed_threshold": round(closed_thr, 4),
            "blinks": blinks,
            "motion_score": round(motion_score, 5),
            "screen_artifact_score": round(screen_score, 4),
        })
        return stats
    finally:
        try:
            landmarker.close()
        except (RuntimeError, ValueError, IOError):  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_liveness(frame_burst) -> ModuleResult:
    """Run multi-signal liveness on a short webcam frame burst.

    Signature for the FastAPI route owner:
        run_liveness(frame_burst) -> ModuleResult

    ``frame_burst`` is one of:
      * a list of frame images (paths, BGR ndarrays, or PIL Images),
      * a video file path (decoded into frames), or
      * a single still (tolerated but low-confidence).

    Returns "ok" or "inconclusive". ``raw_output['live']`` is a bool whenever
    status == "ok". Never raises.
    """
    try:
        frames = _collect_frames(frame_burst)
    except Exception as exc:  # noqa: BLE001
        return inconclusive_result(MODULE_NAME, exc)

    if len(frames) < MIN_BURST_FRAMES:
        # not a real burst -> mark inconclusive (caller should supply a burst)
        return inconclusive_result(
            MODULE_NAME,
            f"expected a frame burst (>= {MIN_BURST_FRAMES} frames); got {len(frames)}",
        )

    if not os.path.exists(_FACELANDMARKER_TASK):
        return inconclusive_result(
            MODULE_NAME,
            "liveness engine model (face_landmarker.task) is not installed — "
            "run `bash scripts/setup_vendor.sh` (or re-clone so the committed "
            "model is present) and retry",
        )

    try:
        stats = _analyse_burst(frames)
    except Exception as exc:  # noqa: BLE001
        return inconclusive_result(MODULE_NAME, exc)

    if stats["n_landmarks"] == 0:
        return inconclusive_result(
            MODULE_NAME, "no facial landmarks found across the burst"
        )

    if stats["coverage"] < MIN_COVERAGE:
        return inconclusive_result(
            MODULE_NAME,
            f"face detected in only {int(stats['coverage'] * 100)}% of frames "
            f"(min {int(MIN_COVERAGE * 100)}%) — retake keeping the face in frame",
        )

    blinks = stats["blinks"]
    motion = stats["motion_score"] or 0.0
    screen = stats["screen_artifact_score"] or 0.0
    coverage = stats["coverage"]

    spoof_signals = []
    reason = None

    # --- must a score be computed from -> decision logic -------------------
    still = motion < STATIC_MOTION

    if still and blinks == 0:
        live = False
        score = 0.08
        reason = "no facial motion and no blink detected — burst looks like a " \
                 "still image (printed photo or frozen screen frame)"
        spoof_signals.append("static_sequence")
    elif screen >= SCREEN_SPOOF:
        live = False
        score = 0.10
        reason = "display-screen artifacts (moire/pixel-grid) detected — " \
                 "suspected photo/video replay from a monitor"
        spoof_signals.append("screen_replay")
        spoof_signals.append("display_artifacts")
    else:
        blink_signal = min(blinks, 2) / 2.0
        motion_signal = float(np.clip(motion / MOTION_REF, 0.0, 1.0))
        if blinks == 0:
            # motion alone can certify liveness, but require a higher bar
            score = 0.45 * motion_signal + 0.25 * (1.0 - screen) + 0.20 * coverage
        else:
            score = 0.55 * max(blink_signal, motion_signal) \
                + 0.25 * (1.0 - screen) + 0.20 * coverage
        live = bool(score >= LIVE_THRESHOLD)
        if not live:
            reason = "liveness signals (blink/motion) below confidence threshold"
            spoof_signals.append("weak_signals")

    liveness_score = round(float(min(max(score, 0.0), 1.0)), 4)

    raw = {
        "liveness_score": liveness_score,
        "live": live,
        "blink_count": blinks,
        "ear_stats": {
            "mean": stats["ear_mean"],
            "min": stats["ear_min"],
            "max": stats["ear_max"],
            "swing": stats["ear_swing"],
            "eye_closed_threshold": stats["eye_closed_threshold"],
        },
        "motion_score": stats["motion_score"],
        "screen_artifact_score": stats["screen_artifact_score"],
        "face_coverage": stats["coverage"],
        "spoof_signals": spoof_signals,
        "frames_analysed": stats["n_frames"],
        "frames_with_landmarks": stats["n_landmarks"],
        "method": "multi_signal_frame_burst",
        "decision": reason or ("LIVE" if live else "NOT LIVE"),
    }
    return ok_result(MODULE_NAME, liveness_score, raw, evidence_uri=None)