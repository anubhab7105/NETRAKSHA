"""Tests for iris pipeline — RGB prototype (EXPERIMENTAL, UNCALIBRATED).

Thresholds (Hamming 0.32, low-conf band 0.28–0.36 per pipeline/thresholds.json)
are prototype placeholders tuned on synthetic data — NOT production-validated.
Re-calibrate on a held-out NIR set before any production use. Tests below pin
the boundary behavior so a silent threshold drift fails loudly.
"""

import pathlib
import numpy as np
import cv2
import pytest

from backend.biometric.iris.provider import get_provider
from backend.biometric.iris.matcher import hamming_distance, match_templates

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

def test_iris_provider_rgb_enroll():
    prov = get_provider("rgb")

    img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.circle(img, (50, 50), 30, (255, 255, 255), -1)
    cv2.circle(img, (50, 50), 15, (0, 0, 0), -1)
    result = prov.enroll(img, eye="left")

    assert "quality" in result

def test_iris_hamming():
    a = b"\x00\xff\x00\xff" * 128
    b = b"\x00\xff\x00\xff" * 128
    m = b"\xff" * 512
    dist = hamming_distance(a, m, b, m)
    assert dist == 0.0

    c = b"\xff\x00\xff\x00" * 128
    dist2 = hamming_distance(a, m, c, m)
    assert dist2 > 0.5

def test_iris_match_decision():
    # NOTE: near-constant codes are degenerate (insufficient texture) and
    # verify as INCONCLUSIVE — use textured half/half codes for MATCH/MISMATCH.
    m = b"\xff" * 512
    textured = bytes([0x00] * 256 + [0xFF] * 256)
    res = match_templates(textured, m, textured, m, threshold=0.32)
    assert res["match"] is True
    assert res["decision"] == "MATCH"

    flipped = bytes([0xFF] * 256 + [0x00] * 256)
    res2 = match_templates(textured, m, flipped, m, threshold=0.32)
    assert res2["match"] is False
    assert res2["decision"] == "MISMATCH"

def test_iris_no_eye():
    prov = get_provider("rgb")
    img = np.zeros((50, 50, 3), dtype=np.uint8)
    res = prov.enroll(img)

    assert "quality" in res

def test_nir_provider_stub():
    prov = get_provider("nir")
    assert prov.name == "NIRProvider"
    res = prov.enroll(np.zeros((100,100,3), dtype=np.uint8))
    assert res["quality"]["usable"] is False


def test_iris_thresholds_match_single_source():
    import json
    import pathlib

    from pipeline.common import load_thresholds

    thr = load_thresholds()
    assert thr["iris_match"] == 0.32
    assert thr["iris_low_conf_low"] == 0.28
    assert thr["iris_low_conf_high"] == 0.36
    # The prototype marker lives in thresholds.json (the loader only carries
    # numeric decision keys) — both must agree this is uncalibrated.
    raw = json.loads((pathlib.Path(__file__).resolve().parent.parent
                      / "pipeline" / "thresholds.json").read_text())
    assert raw["iris_match"] == 0.32
    assert raw.get("iris_calibration") == "uncalibrated-prototype"


def _templates_at_distance(dist: float, n: int = 512):
    """Build (probe, ref, mask) with an exact byte-level Hamming distance.

    NOTE: matcher.hamming_distance compares uint8 BYTES (``a != b``), not
    bits — so flipping ``round(dist*n)`` whole bytes yields distance ≈ dist.
    Codes are half-0x00/half-0xFF (frac 0xFF = 0.5) to stay clear of the
    degenerate-template gate (frac <0.15 or >0.85 → INCONCLUSIVE).
    """
    import random

    rng = random.Random(int(dist * 10000) + 7)
    probe = bytes([0x00] * (n // 2) + [0xFF] * (n - n // 2))
    idx = list(range(n))
    rng.shuffle(idx)
    n_flip = int(round(dist * n))
    flip = set(idx[:n_flip])
    ref = bytes(
        (0x01 if (b == 0x00 and i in flip) else (0xFE if (b == 0xFF and i in flip) else b))
        for i, b in enumerate(probe)
    )
    mask = b"\xff" * n
    return bytes(probe), mask, bytes(ref), mask


def test_iris_boundary_match_mismatch_bands():
    m = b"\xff" * 512
    # Textured identical codes match (non-degenerate: half 0x00 / half 0xFF).
    textured = bytes([0x00] * 256 + [0xFF] * 256)
    res = match_templates(textured, m, textured, m, threshold=0.32)
    assert res["match"] is True and res["decision"] == "MATCH"
    # Fully differing textured codes mismatch (halves swapped: distance 1.0,
    # still 50% 0xFF so the degenerate gate stays clear).
    flipped = bytes([0xFF] * 256 + [0x00] * 256)
    res = match_templates(textured, m, flipped, m, threshold=0.32)
    assert res["match"] is False and res["decision"] == "MISMATCH"


def test_iris_low_conf_band_is_inconclusive():
    # A mid-band distance (~0.32) must NOT decide — prototype routes it to
    # manual review as INCONCLUSIVE with match=None.
    probe, pmask, ref, rmask = _templates_at_distance(0.32)
    res = match_templates(probe, pmask, ref, rmask, threshold=0.32)
    assert res["distance"] is not None
    assert 0.28 <= res["distance"] <= 0.36
    assert res["decision"] == "INCONCLUSIVE"
    assert res["match"] is None
    assert res["low_confidence"] is True


def test_iris_length_mismatch_fails_closed():
    m = b"\xff" * 512
    assert hamming_distance(b"\x00" * 512, m, b"\x00" * 256, b"\xff" * 256) == 1.0
    res = match_templates(b"\x00" * 512, m, b"\x00" * 256, b"\xff" * 256)
    assert res["decision"] in ("MISMATCH", "INCONCLUSIVE")
