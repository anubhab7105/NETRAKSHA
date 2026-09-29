
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


CHALLENGE_TYPES = ["blink", "head_turn", "mouth_open"]

HEAD_YAW_THRESHOLD = 0.30

MOUTH_OPEN_THRESHOLD = 0.04


MIN_BURST_FRAMES = 3

MIN_COVERAGE = 0.5

STATIC_MOTION = 0.002

MOTION_REF = 0.015

SCREEN_SPOOF = 0.60

LIVE_THRESHOLD = 0.45

BLINK_DEPTH = 0.01


_FACELANDMARKER_TASK = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "vendor",
    "models",
    "face_landmarker.task",
)


_LEFT_EYE = [33, 160, 158, 133, 153, 144]
_RIGHT_EYE = [362, 385, 387, 263, 373, 380]






def _ear(landmarks, indices) -> Optional[float]:
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
    if isinstance(burst_input, (str, pathlib.Path, os.PathLike)):
        p = pathlib.Path(burst_input)
        if p.suffix.lower() in {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}:
            return _frames_from_video(p)

        return [load_image(p)]

    if isinstance(burst_input, (list, tuple)) and len(burst_input) > 0:

        if isinstance(burst_input[0], (str, pathlib.Path, os.PathLike)):
            return [load_image(x) for x in burst_input]

        if isinstance(burst_input[0], np.ndarray):
            return [x.astype(np.uint8) for x in burst_input]

        return [load_image(x) for x in burst_input]


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






def _extract_frame_features(landmarker, mp, frame: np.ndarray):
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


def _mouth_open_ratio(landmarks) -> Optional[float]:
    try:

        upper = np.array([landmarks[13].x, landmarks[13].y])
        lower = np.array([landmarks[14].x, landmarks[14].y])
        left = np.array([landmarks[78].x, landmarks[78].y])
        right = np.array([landmarks[308].x, landmarks[308].y])
        mouth_w = np.linalg.norm(right - left) + 1e-6
        opening = np.linalg.norm(lower - upper) / mouth_w
        return float(opening)
    except Exception:
        return None


def _head_yaw(landmarks) -> Optional[float]:
    try:
        from .face_quality import yaw_proxy_from_kps
        kps = [(landmarks[i].x, landmarks[i].y) for i in [33, 263, 1, 61, 291]]

        pts = [landmarks[33], landmarks[263], landmarks[1]]

        import numpy as np
        left = np.array([landmarks[33].x, landmarks[33].y])
        right = np.array([landmarks[263].x, landmarks[263].y])
        nose = np.array([landmarks[1].x, landmarks[1].y])
        eye_dist = np.linalg.norm(right - left) + 1e-6
        mid_x = (left[0] + right[0]) / 2.0
        return float((nose[0] - mid_x) / eye_dist)
    except Exception:
        return None


def _screen_artifact_score(frame: np.ndarray, bbox) -> float:
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

        mag = np.log1p(spectrum)

        cy, cx = 64, 64
        ys, xs = np.mgrid[0:128, 0:128]
        r = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2) / 64.0
        total_mask = r >= 3.0 / 64.0


        high_mask = (r >= 0.35) & (r <= 1.0)
        total_energy = float(mag[total_mask].sum()) + 1e-9
        high_energy = float(mag[high_mask].sum())
        high_fraction = high_energy / total_energy


        band = (r >= 0.20) & (r <= 0.80)
        band_vals = mag[band]
        if band_vals.size == 0:
            peakiness = 1.0
        else:
            peakiness = float(band_vals.max()) / (float(band_vals.mean()) + 1e-9)

        hf_signal = np.clip((high_fraction - 0.10) / 0.20, 0.0, 1.0)
        pk_signal = np.clip((peakiness - 2.0) / 5.0, 0.0, 1.0)
        return float(0.5 * hf_signal + 0.5 * pk_signal)
    except Exception:
        return 0.0






def _analyse_burst(frames: List[np.ndarray]) -> dict:
    import mediapipe as mp

    landmarker = _face_mesh()
    try:
        features = []
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
            "head_yaw_max": None,
            "head_turn_detected": False,
            "mouth_open_max": None,
            "mouth_open_detected": False,
        }

        if n_landmarks == 0:
            return stats


        arr = np.asarray([ear_series[i] for i in valid_idx], dtype=np.float64)
        baseline = float(np.percentile(arr, 75))


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

                rel_drop = baseline - run_min
                if rel_drop >= baseline * 0.25:
                    blinks += 1
                i = j
            else:
                i += 1


        head_yaws = []
        mouth_opens = []
        for idx in valid_idx:
            feat = features[idx]




            try:
                pts = feat[1]

                left = pts[33]
                right = pts[263]
                nose = pts[1]
                eye_dist = float(np.linalg.norm(right - left)) + 1e-6
                mid_x = (left[0] + right[0]) / 2.0
                yaw = float((nose[0] - mid_x) / eye_dist)
                head_yaws.append(abs(yaw))
            except Exception:
                pass
            try:


                upper = pts[13]
                lower = pts[14]
                left_m = pts[78]
                right_m = pts[308]
                mouth_w = float(np.linalg.norm(right_m - left_m)) + 1e-6
                opening = float(np.linalg.norm(lower - upper) / mouth_w)
                mouth_opens.append(opening)
            except Exception:
                pass
        head_yaw_max = float(max(head_yaws)) if head_yaws else 0.0
        mouth_open_max = float(max(mouth_opens)) if mouth_opens else 0.0


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
            "head_yaw_max": round(head_yaw_max, 3),
            "head_turn_detected": bool(head_yaw_max >= HEAD_YAW_THRESHOLD),
            "mouth_open_max": round(mouth_open_max, 3),
            "mouth_open_detected": bool(mouth_open_max >= MOUTH_OPEN_THRESHOLD),
        })
        return stats
    finally:
        try:
            landmarker.close()
        except (RuntimeError, ValueError, IOError):
            pass






def run_liveness(frame_burst, challenge_type: str = "blink") -> ModuleResult:
    try:
        frames = _collect_frames(frame_burst)
    except Exception as exc:
        return inconclusive_result(MODULE_NAME, exc)

    if len(frames) < MIN_BURST_FRAMES:

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
    except Exception as exc:
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
    head_turn = stats.get("head_turn_detected", False)
    mouth_open = stats.get("mouth_open_detected", False)

    challenge = (challenge_type or "blink").strip().lower()
    if challenge not in CHALLENGE_TYPES:
        challenge = "blink"

    spoof_signals = []
    reason = None


    still = motion < STATIC_MOTION


    challenge_ok = True
    challenge_reason = None
    if challenge == "blink" and blinks == 0:

        challenge_ok = False
        challenge_reason = "blink challenge not observed — no blink detected"
    elif challenge == "head_turn" and not head_turn:
        challenge_ok = False
        challenge_reason = "head-turn challenge not observed — no significant yaw detected"
    elif challenge == "mouth_open" and not mouth_open:
        challenge_ok = False
        challenge_reason = "mouth-open challenge not observed — mouth did not open sufficiently"
    elif challenge == "smile" and not mouth_open:

        challenge_ok = False
        challenge_reason = "smile challenge not observed"

    observed = []
    if blinks > 0:
        observed.append(f"blink x{blinks}")
    if head_turn:
        observed.append("head_turn")
    if mouth_open:
        observed.append("mouth_open")

    if still and blinks == 0 and not head_turn and not mouth_open:
        live = False
        score = 0.08
        reason = challenge_reason or "no facial motion and no blink/head/mouth activity — burst looks like a " \
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

        challenge_signal = 1.0 if (blinks > 0 or head_turn or mouth_open) else 0.0
        if blinks == 0 and not head_turn and not mouth_open:

            score = 0.45 * motion_signal + 0.25 * (1.0 - screen) + 0.20 * coverage
        else:
            score = 0.55 * max(blink_signal, motion_signal, challenge_signal) \
                + 0.25 * (1.0 - screen) + 0.20 * coverage
        live = bool(score >= LIVE_THRESHOLD)
        if live and not challenge_ok:



            spoof_signals.append(f"challenge_not_observed:{challenge}")
            reason = (f"LIVE via {', '.join(observed)} but the assigned "
                      f"'{challenge}' challenge was not performed")
        if not live:
            reason = challenge_reason or "liveness signals (blink/motion/head/mouth) below confidence threshold"
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
        "head_yaw_max": stats.get("head_yaw_max"),
        "head_turn_detected": stats.get("head_turn_detected"),
        "mouth_open_max": stats.get("mouth_open_max"),
        "mouth_open_detected": stats.get("mouth_open_detected"),
        "challenge_type": challenge,
        "challenge_passed": live and challenge_ok,
        "face_coverage": stats["coverage"],
        "spoof_signals": spoof_signals,
        "frames_analysed": stats["n_frames"],
        "frames_with_landmarks": stats["n_landmarks"],
        "method": "multi_signal_frame_burst",
        "decision": reason or ("LIVE" if live else "NOT LIVE"),
    }
    return ok_result(MODULE_NAME, liveness_score, raw, evidence_uri=None)