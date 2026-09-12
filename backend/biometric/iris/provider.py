"""BiometricProvider abstraction for iris verification.

RGBProvider is the smartphone prototype (visible-light).
NIRProvider is a future stub for dedicated IR hardware.

The architecture isolates the pipeline so the same enroll/verify
calls work for both, and the risk engine only sees the provider's
output, not its internals.
"""

from __future__ import annotations

import abc
from typing import Dict, Any, Optional

class BiometricProvider(abc.ABC):
    """Abstract iris provider."""

    @abc.abstractmethod
    def enroll(self, eye_image, eye: str = "left") -> Dict[str, Any]:
        """Process an eye image into a template. Returns {template, mask, quality}."""
        raise NotImplementedError

    @abc.abstractmethod
    def verify(self, probe_image, reference_template: bytes, reference_mask: bytes) -> Dict[str, Any]:
        """Compare a probe eye image against a stored template."""
        raise NotImplementedError

    @abc.abstractmethod
    def quality(self, eye_image) -> Dict[str, Any]:
        """Assess iris image quality."""
        raise NotImplementedError

    @abc.abstractmethod
    def liveness(self, eye_frames) -> Dict[str, Any]:
        """Iris PAD on a short eye frame burst."""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def version(self) -> str:
        raise NotImplementedError


class RGBProvider(BiometricProvider):
    """Visible-light smartphone iris (prototype).

    Uses classical CV (Hough circles + Gabor) on RGB. Not equivalent to NIR,
    but allows the full workflow on Android Chrome without specialized hardware.
    Documented as prototype/research grade.
    """

    name = "RGBProvider"
    version = "1.0-rgb-prototype"

    def enroll(self, eye_image, eye: str = "left") -> Dict[str, Any]:
        from .quality import assess_iris_quality
        from .segmenter import segment_iris
        from .normalizer import normalize_iris
        from .encoder import encode_iris
        # 1. quality gate
        q = assess_iris_quality(eye_image)
        if not q.get("usable"):
            return {"template": None, "mask": None, "quality": q, "error": "poor_quality"}
        # 2. segment
        seg = segment_iris(eye_image)
        if seg.get("status") != "ok":
            return {"template": None, "mask": None, "quality": q, "error": seg.get("reason", "segmentation_failed")}
        # 3. normalize
        norm = normalize_iris(eye_image, seg["pupil"], seg["iris"], seg.get("mask"))
        if norm.get("status") != "ok":
            return {"template": None, "mask": None, "quality": q, "error": "normalization_failed"}
        # 4. encode
        enc = encode_iris(norm["normalized"], norm.get("mask"))
        return {
            "template": enc.get("template"),
            "mask": enc.get("mask"),
            "quality": q,
            "segment": seg,
            "normalized": norm,
        }

    def verify(self, probe_image, reference_template: bytes, reference_mask: bytes) -> Dict[str, Any]:
        from .matcher import match_templates
        # Enroll the probe to get its template, then match
        probe = self.enroll(probe_image)
        if not probe.get("template"):
            return {"match": None, "distance": None, "quality": probe.get("quality"), "decision": "INCONCLUSIVE"}
        return match_templates(probe["template"], probe["mask"], reference_template, reference_mask)

    def quality(self, eye_image) -> Dict[str, Any]:
        from .quality import assess_iris_quality
        return assess_iris_quality(eye_image)

    def liveness(self, eye_frames) -> Dict[str, Any]:
        from .liveness import check_iris_liveness
        return check_iris_liveness(eye_frames)


class NIRProvider(BiometricProvider):
    """Future NIR hardware provider — stub.

    Real NIR acquisition requires 850nm illumination and an IR sensor
    (e.g., IriTech IriShield). This stub documents the interface and
    returns inconclusive so the system remains functional until hardware
    is integrated. Do not pretend RGB is equivalent to NIR.
    """

    name = "NIRProvider"
    version = "0.1-stub"

    def enroll(self, eye_image, eye: str = "left") -> Dict[str, Any]:
        return {"template": None, "mask": None, "quality": {"usable": False, "reason": "NIR hardware not connected"}, "error": "NIR not available"}

    def verify(self, probe_image, reference_template: bytes, reference_mask: bytes) -> Dict[str, Any]:
        return {"match": None, "distance": None, "decision": "INCONCLUSIVE", "reason": "NIR not available"}

    def quality(self, eye_image) -> Dict[str, Any]:
        return {"quality": 0.0, "usable": False, "reason": "NIR not available"}

    def liveness(self, eye_frames) -> Dict[str, Any]:
        return {"passed": None, "confidence": 0.0, "reason": "NIR not available"}


def get_provider(name: str = "rgb") -> BiometricProvider:
    """Factory — 'rgb' (default) or 'nir'."""
    name = (name or "rgb").strip().lower()
    if name in ("nir", "ir"):
        return NIRProvider()
    return RGBProvider()
