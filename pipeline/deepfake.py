
from __future__ import annotations

import numpy as np

from .common import (
    ModuleResult,
    inconclusive_result,
    load_image,
    ok_result,
)

MODULE_NAME = "deepfake"


def _radial_power_spectrum(magnitude: np.ndarray) -> np.ndarray:
    h, w = magnitude.shape
    cy, cx = h // 2, w // 2
    yy, xx = np.mgrid[0:h, 0:w]
    rr = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2).astype(np.int32)
    max_r = min(cy, cx)
    rr = np.clip(rr, 0, max_r - 1)
    power = np.zeros(max_r, dtype=np.float64)
    counts = np.zeros(max_r, dtype=np.float64)
    np.add.at(power, rr, magnitude)
    np.add.at(counts, rr, 1)
    return np.divide(power, counts, out=np.zeros_like(power), where=counts > 0)


def _fft_metrics(face_bgr: np.ndarray) -> dict:
    import cv2

    gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)


    h, w = gray.shape
    win = cv2.createHanningWindow((w, h), cv2.CV_64F)
    windowed = gray.astype(np.float64) * win

    f = np.fft.fft2(windowed)
    fshift = np.fft.fftshift(f)
    magnitude = np.log1p(np.abs(fshift))

    power = _radial_power_spectrum(magnitude)
    r = np.arange(len(power), dtype=np.float64)
    Nyquist = len(power) - 1
    if Nyquist < 1:
        return {"error": "image too small"}


    low = power[ : max(1, int(Nyquist * 0.2))]
    mid = power[int(Nyquist * 0.2) : int(Nyquist * 0.6)]
    high = power[int(Nyquist * 0.6) : int(Nyquist * 0.95)]
    hf_energy = np.sum(high) if len(high) else 0.0
    total_energy = np.sum(power[1:]) + 1e-9
    hf_fraction = hf_energy / total_energy



    band = power[int(Nyquist * 0.3) : int(Nyquist * 0.85)]
    peakedness = 0.0
    if len(band) >= 4:
        base = np.percentile(band, 25)
        peakedness = float(np.max(band) / (base + 1e-9))


    rolloff_ratio = float((np.mean(high) + 1e-9) / (np.mean(low) + 1e-9))

    return {
        "high_frequency_fraction": hf_fraction,
        "spectral_peakedness": peakedness,
        "rolloff_ratio": rolloff_ratio,
        "low_band_mean": float(np.mean(low)),
        "high_band_mean": float(np.mean(high)),
    }


def run_deepfake(face_image) -> ModuleResult:
    try:
        img = load_image(face_image)
        if img is None or img.size == 0:
            raise ValueError("empty image")
    except Exception as exc:
        return inconclusive_result(MODULE_NAME, exc)

    try:
        metrics = _fft_metrics(img)
        if "error" in metrics:
            return inconclusive_result(MODULE_NAME, metrics["error"])
    except Exception as exc:
        return inconclusive_result(MODULE_NAME, exc)

    hf = metrics["high_frequency_fraction"]
    peak = metrics["spectral_peakedness"]
    roll = metrics["rolloff_ratio"]



    score_hf = np.clip((hf - 0.10) / 0.25, 0.0, 1.0)
    score_peak = np.clip((peak - 2.0) / 6.0, 0.0, 1.0)
    score_roll = np.clip((roll - 0.5) / 3.0, 0.0, 1.0)
    deepfake_score = round(
        float(0.5 * score_hf + 0.3 * score_peak + 0.2 * score_roll), 4
    )

    raw = {
        "deepfake_score": deepfake_score,
        "method": "fft_frequency_artifact_heuristic",
        "classifier_integrated": False,
        "metrics": metrics,
    }
    return ok_result(MODULE_NAME, deepfake_score, raw, evidence_uri=None)
