"""Pipeline facade for iris — delegates to backend/biometric/iris.

Fail-closed: the backend biometric stack is imported lazily (so importing
this module never pulls cv2/mediapipe/onnx), every entry point catches all
exceptions and returns an INCONCLUSIVE dict (never raises, never a
ModuleResult inversion — plain dicts, match=None, decision INCONCLUSIVE).
Iris Hamming thresholds in thresholds.json are prototype placeholders
(uncalibrated-prototype): callers must treat iris as advisory and gate on
quality/liveness before any Red (see risk_engine).
"""

from __future__ import annotations
from typing import Dict, Any, Optional


def _get_backend_provider(provider: str = "rgb"):
    from backend.biometric.iris.provider import get_provider

    return get_provider(provider)


def _inconclusive(reason: str, eye: str = "left", provider: str = "rgb") -> Dict[str, Any]:
    return {
        "match": None,
        "decision": "INCONCLUSIVE",
        "reason": str(reason)[:200],
        "eye": eye,
        "source": "none",
        "provider": provider,
    }


def run_iris_enrollment(eye_image, eye: str = "left", provider: str = "rgb") -> Dict[str, Any]:
    """Enroll an eye image to a template. Never raises."""
    try:
        prov = _get_backend_provider(provider)
        return prov.enroll(eye_image, eye=eye)
    except Exception as exc:
        return _inconclusive(f"{type(exc).__name__}: {str(exc)[:120]}", eye, provider)


def run_iris_verification(
    probe_image, reference_template: bytes, reference_mask: bytes, provider: str = "rgb"
) -> Dict[str, Any]:
    """Verify a probe against a reference template. Never raises."""
    try:
        prov = _get_backend_provider(provider)
        return prov.verify(probe_image, reference_template, reference_mask)
    except Exception as exc:
        return _inconclusive(f"{type(exc).__name__}: {str(exc)[:120]}", "left", provider)


def run_iris_quality(eye_image, provider: str = "rgb") -> Dict[str, Any]:
    """Assess iris image quality. Never raises."""
    try:
        prov = _get_backend_provider(provider)
        return prov.quality(eye_image)
    except Exception as exc:
        return {"usable": None, "quality": None,
                "reason": f"{type(exc).__name__}: {str(exc)[:120]}"[:200]}


def run_iris_liveness(eye_frames, provider: str = "rgb") -> Dict[str, Any]:
    """Iris liveness (PAD) over eye frames. Never raises."""
    try:
        prov = _get_backend_provider(provider)
        return prov.liveness(eye_frames)
    except Exception as exc:
        return {"passed": None,
                "reason": f"{type(exc).__name__}: {str(exc)[:120]}"[:200]}
