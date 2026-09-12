"""Iris template matching via Hamming distance."""

from __future__ import annotations
import numpy as np
from typing import Dict, Any

def hamming_distance(template_a: bytes, mask_a: bytes, template_b: bytes, mask_b: bytes) -> float:
    """Compute normalized Hamming distance between two binary templates."""
    try:
        a = np.frombuffer(template_a, dtype=np.uint8)
        b = np.frombuffer(template_b, dtype=np.uint8)
        ma = np.frombuffer(mask_a, dtype=np.uint8) if mask_a else np.ones_like(a) * 255
        mb = np.frombuffer(mask_b, dtype=np.uint8) if mask_b else np.ones_like(b) * 255
        # Ensure same length
        n = min(len(a), len(b), len(ma), len(mb))
        a, b, ma, mb = a[:n], b[:n], ma[:n], mb[:n]
        # Valid bits where both masks are 255
        valid = (ma == 255) & (mb == 255)
        if valid.sum() == 0:
            return 1.0
        # Compare bits
        diff = (a != b) & valid
        return float(diff.sum() / valid.sum())
    except Exception:
        return 1.0

def match_templates(probe_template: bytes, probe_mask: bytes, ref_template: bytes, ref_mask: bytes, threshold: float = 0.32) -> Dict[str, Any]:
    """Match probe against reference. Threshold <0.32 is initial prototype (uncalibrated)."""
    try:
        dist = hamming_distance(probe_template, probe_mask, ref_template, ref_mask)
        # Low-confidence band 0.28-0.36
        low_conf = 0.28 <= dist <= 0.36
        if dist < 0.28:
            decision = "MATCH"
            match = True
        elif dist > 0.36:
            decision = "MISMATCH"
            match = False
        else:
            decision = "INCONCLUSIVE"
            match = None
        # Strict threshold
        strict_match = dist < threshold
        return {
            "match": match,
            "strict_match": strict_match,
            "distance": round(float(dist), 4),
            "threshold": threshold,
            "low_confidence": low_conf,
            "decision": decision,
        }
    except Exception as e:
        return {"match": None, "distance": None, "decision": "INCONCLUSIVE", "error": str(e)[:60]}
