"""Module 5 — Liveness detection.

Approach (Techspec.md §3): blink detection via Eye-Aspect-Ratio (EAR) across a
short webcam frame burst, using mediapipe face-mesh landmarks.

Input: a SHORT FRAME BURST, not a single still —
  * a list of image paths / PIL / BGR ndarrays, or
  * a video file path (several frames decoded from it), or
  * a path to a single image is tolerated but yields low confidence (we flag it).

For each frame we localise the eyes with mediapipe and compute EAR. A genuine
blink is a rapid drop in EAR below a threshold followed by recovery. Presence of
>=1 blink plus coherent temporal variance -> higher liveness.

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
    single_log,
)

MODULE_NAME = "liveness"

# EAR below this is "closed"; blink = closed -> open transition.
EAR_EYE_CLOSED = 0.21
# minimum number of frames required to be considered a real burst
MIN_BURST_FRAMES = 3
# minimum EAR swing to count as a blink (avoids noise)
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


def _detect_blinks(frames: List[np.ndarray]) -> dict:
    landmarker = None
    try:
        import mediapipe as mp

        landmarker = _face_mesh()
        ear_series = []
        for frame in frames:
            rgb = frame[:, :, ::-1] if frame.ndim == 3 and frame.shape[2] == 3 else frame
            results = landmarker.detect(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            )
            if not results or not results.face_landmarks:
                ear_series.append(None)
                continue
            lm = results.face_landmarks[0]
            left = _ear(lm, _LEFT_EYE)
            right = _ear(lm, _RIGHT_EYE)
            if left is None or right is None:
                ear_series.append(None)
            else:
                ear_series.append(float((left + right) / 2.0))
        return _analyse_ear(ear_series)
    finally:
        if landmarker is not None:
            try:
                landmarker.close()
            except Exception:  # noqa: BLE001
                pass


def _analyse_ear(ear_series: List[Optional[float]]) -> dict:
    valid = [e for e in ear_series if e is not None]
    n_frames = len(ear_series)
    n_landmarks = len(valid)

    if n_landmarks == 0:
        return {
            "n_frames": n_frames,
            "n_landmarks": 0,
            "blinks": 0,
            "mean_ear": None,
            "min_ear": None,
            "max_ear": None,
        }

    arr = np.asarray(valid)
    mean_ear = float(np.mean(arr))
    min_ear = float(np.min(arr))
    max_ear = float(np.max(arr))

    # count blink events: each contiguous run of "closed" frames (EAR below
    # threshold), bounded by recovery, counts as one blink if it also produced a
    # meaningful drop (BLINK_DEPTH) to reject noisy single-frame flickers.
    blinks = 0
    i = 0
    while i < len(arr):
        if arr[i] < EAR_EYE_CLOSED:
            j = i
            run_min = arr[i]
            while j < len(arr) and arr[j] < EAR_EYE_CLOSED:
                run_min = min(run_min, arr[j])
                j += 1
            if (EAR_EYE_CLOSED - run_min) >= BLINK_DEPTH:
                blinks += 1
            i = j
        else:
            i += 1

    swing = max_ear - min_ear
    return {
        "n_frames": n_frames,
        "n_landmarks": n_landmarks,
        "blinks": blinks,
        "mean_ear": round(mean_ear, 4),
        "min_ear": round(min_ear, 4),
        "max_ear": round(max_ear, 4),
        "swing": round(swing, 4),
        "eye_closed_threshold": EAR_EYE_CLOSED,
    }


def run_liveness(frame_burst) -> ModuleResult:
    """Run blink/EAR liveness on a short webcam frame burst.

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

    try:
        stats = _detect_blinks(frames)
    except Exception as exc:  # noqa: BLE001
        return inconclusive_result(MODULE_NAME, exc)

    if stats["n_landmarks"] == 0:
        return inconclusive_result(
            MODULE_NAME, "no facial landmarks found across the burst"
        )

    # --- liveness score (0-1), live bool ------------------------------------
    blinks = min(stats["blinks"] or 0, 3)
    blink_signal = blinks / 3.0
    # temporal variance: a real video shows EAR swing; a static photo does not.
    variance_signal = np.clip((stats["swing"] or 0.0) / 0.25, 0.0, 1.0)

    liveness_score = round(float(0.6 * blink_signal + 0.4 * variance_signal), 4)
    live = bool(liveness_score >= 0.30)

    raw = {
        "liveness_score": liveness_score,
        "live": live,
        "blink_count": stats["blinks"],
        "ear_stats": {
            "mean": stats["mean_ear"],
            "min": stats["min_ear"],
            "max": stats["max_ear"],
            "swing": stats["swing"],
            "eye_closed_threshold": EAR_EYE_CLOSED,
        },
        "frames_analysed": stats["n_frames"],
        "frames_with_landmarks": stats["n_landmarks"],
        "method": "ear_blink_frame_burst",
    }
    return ok_result(MODULE_NAME, liveness_score, raw, evidence_uri=None)
