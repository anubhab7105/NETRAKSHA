"""Gabor/Log-Gabor encoding to binary iris code."""

from __future__ import annotations
import cv2
import numpy as np
from typing import Dict, Any

def encode_iris(normalized: np.ndarray, mask=None) -> Dict[str, Any]:
    """Gabor filter the normalized iris to a binary template + mask."""
    try:
        # Convert to grayscale
        if normalized.ndim == 3:
            gray = cv2.cvtColor(normalized, cv2.COLOR_BGR2GRAY)
        else:
            gray = normalized
        # Simple Gabor-like encoding: use 2D Gabor filter bank
        # For prototype, use Log-Gabor via FFT or just thresholded Gabor
        # Use a single Gabor filter as baseline
        ksize = 18
        sigma = 3.0
        theta = 0
        lambd = 12.0
        gamma = 0.5
        kernel = cv2.getGaborKernel((ksize, ksize), sigma, theta, lambd, gamma, 0, ktype=cv2.CV_32F)
        filtered = cv2.filter2D(gray.astype(np.float32), cv2.CV_32F, kernel)
        # Binarize: positive vs negative
        template = (filtered > 0).astype(np.uint8) * 255
        # Downsample to 512 bits (64x8) for compactness
        small = cv2.resize(template, (64, 8), interpolation=cv2.INTER_NEAREST)
        # Pack to bytes
        _, buf = cv2.imencode('.png', small)  # use PNG as container for prototype
        # For matching, keep as bytes
        # Use raw bytes of the binary image
        template_bytes = small.tobytes()
        # Mask: use provided or create from normalized mask
        if mask is not None:
            mask_small = cv2.resize(mask, (64, 8), interpolation=cv2.INTER_NEAREST)
            _, m_buf = cv2.imencode('.png', mask_small)
            mask_bytes = mask_small.tobytes()
        else:
            mask_bytes = (np.ones_like(small) * 255).tobytes()
        return {"template": template_bytes, "mask": mask_bytes, "quality": 0.7}
    except Exception as e:
        return {"template": None, "mask": None, "error": str(e)[:80]}
