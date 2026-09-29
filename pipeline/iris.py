
from __future__ import annotations
from typing import Dict, Any, Optional
import numpy as np


from backend.biometric.iris.provider import get_provider, RGBProvider, NIRProvider

def run_iris_enrollment(eye_image, eye: str = "left", provider: str = "rgb") -> Dict[str, Any]:
    prov = get_provider(provider)
    return prov.enroll(eye_image, eye=eye)

def run_iris_verification(probe_image, reference_template: bytes, reference_mask: bytes, provider: str = "rgb") -> Dict[str, Any]:
    prov = get_provider(provider)
    return prov.verify(probe_image, reference_template, reference_mask)

def run_iris_quality(eye_image, provider: str = "rgb") -> Dict[str, Any]:
    prov = get_provider(provider)
    return prov.quality(eye_image)

def run_iris_liveness(eye_frames, provider: str = "rgb") -> Dict[str, Any]:
    prov = get_provider(provider)
    return prov.liveness(eye_frames)
