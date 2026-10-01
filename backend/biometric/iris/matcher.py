"""Iris template matching via Hamming distance."""

from __future__ import annotations
import numpy as np
from typing import Dict, Any

def hamming_distance(template_a: bytes, mask_a: bytes, template_b: bytes, mask_b: bytes) -> float:
    """Compute normalized Hamming distance between two binary templates.

    Length mismatches return 1.0 (no match) instead of truncating to the
    shorter code — silent truncation false-accepts across providers.
    """
    try:
        a = np.frombuffer(template_a, dtype=np.uint8)
        b = np.frombuffer(template_b, dtype=np.uint8)
        ma = np.frombuffer(mask_a, dtype=np.uint8) if mask_a else np.ones_like(a) * 255
        mb = np.frombuffer(mask_b, dtype=np.uint8) if mask_b else np.ones_like(b) * 255

        if not (len(a) == len(b) == len(ma) == len(mb)) or len(a) == 0:
            return 1.0

        valid = (ma == 255) & (mb == 255)
        if valid.sum() == 0:
            return 1.0

        diff = (a != b) & valid
        return float(diff.sum() / valid.sum())
    except Exception:
        return 1.0

def _is_degenerate(template: bytes) -> bool:
    """True when a stored/probe code is near-constant (no iris texture).

    Guards templates minted before the encoder texture gate existed:
    matching them would false-accept at distance ~0.
    """
    try:
        a = np.frombuffer(template, dtype=np.uint8)
        if a.size == 0:
            return True
        frac = float((a == 255).mean())
        return frac < 0.15 or frac > 0.85
    except Exception:
        return True


def match_templates(probe_template: bytes, probe_mask: bytes, ref_template: bytes, ref_mask: bytes, threshold: float = 0.32) -> Dict[str, Any]:
    """Match probe against reference. Threshold <0.32 is initial prototype (uncalibrated)."""
    try:
        if not probe_template or not ref_template:
            return {"match": None, "distance": None, "decision": "INCONCLUSIVE",
                    "error": "missing template"}
        if _is_degenerate(probe_template) or _is_degenerate(ref_template):
            return {"match": None, "distance": None, "decision": "INCONCLUSIVE",
                    "error": "degenerate template (insufficient iris texture)"}
        dist = hamming_distance(probe_template, probe_mask, ref_template, ref_mask)

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
