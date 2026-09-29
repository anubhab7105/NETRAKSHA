
from __future__ import annotations
import cv2
import numpy as np
from typing import Dict, Any, List

def check_iris_liveness(eye_frames) -> Dict[str, Any]:
    try:
        from pipeline.common import load_image
        frames = []
        if isinstance(eye_frames, (list, tuple)):
            for f in eye_frames:
                try:
                    frames.append(load_image(f) if not isinstance(f, np.ndarray) else f)
                except Exception:
                    pass
        else:
            frames.append(load_image(eye_frames))

        if len(frames) < 3:
            return {"passed": None, "confidence": 0.0, "reason": "insufficient frames for iris PAD", "status": "inconclusive"}



        diffs = []
        for i in range(1, len(frames)):
            try:
                gray1 = cv2.cvtColor(frames[i-1], cv2.COLOR_BGR2GRAY)
                gray2 = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)
                gray1 = cv2.resize(gray1, (64, 64))
                gray2 = cv2.resize(gray2, (64, 64))
                diff = float(np.mean(np.abs(gray2.astype(float) - gray1.astype(float))))
                diffs.append(diff)
            except Exception:
                pass
        mean_diff = float(np.mean(diffs)) if diffs else 0.0
        has_movement = mean_diff > 1.5



        try:
            gray = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (64, 64)).astype(float)
            spec = np.abs(np.fft.fftshift(np.fft.fft2(gray)))

            high = float((spec[20:44, 20:44].mean()))
            low = float(spec.mean()) + 1e-6
            screen_score = float(high / low)
            is_screen = screen_score > 1.8
        except Exception:
            is_screen = False
            screen_score = 0.0



        contact_lens_suspected = False

        passed = has_movement and not is_screen
        confidence = 0.7 if passed else 0.3
        if not has_movement:
            confidence = 0.2

        return {
            "passed": passed,
            "confidence": round(confidence, 2),
            "signals": {
                "temporal_movement": round(mean_diff, 2),
                "has_movement": has_movement,
                "screen_score": round(screen_score, 2),
                "is_screen": is_screen,
                "contact_lens_suspected": contact_lens_suspected,
            },
            "issues": [] if passed else (["no_movement"] if not has_movement else ["screen_replay"] if is_screen else ["weak_signals"]),
            "status": "ok" if passed is not None else "inconclusive",
        }
    except Exception as e:
        return {"passed": None, "confidence": 0.0, "reason": str(e)[:60], "status": "inconclusive"}
