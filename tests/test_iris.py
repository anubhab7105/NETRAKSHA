"""Tests for iris pipeline — RGB prototype."""

import pathlib
import numpy as np
import cv2
import pytest

from backend.biometric.iris.provider import get_provider
from backend.biometric.iris.matcher import hamming_distance, match_templates

def test_iris_provider_rgb_enroll():
    prov = get_provider("rgb")
    # Create a synthetic eye image (100x100 with a circle)
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.circle(img, (50, 50), 30, (255, 255, 255), -1)
    cv2.circle(img, (50, 50), 15, (0, 0, 0), -1)
    result = prov.enroll(img, eye="left")
    # Should return a dict with quality, even if segmentation fails on synthetic
    assert "quality" in result

def test_iris_hamming():
    a = b"\x00\xff\x00\xff" * 128  # 512 bytes
    b = b"\x00\xff\x00\xff" * 128
    m = b"\xff" * 512
    dist = hamming_distance(a, m, b, m)
    assert dist == 0.0
    # Flip bits
    c = b"\xff\x00\xff\x00" * 128
    dist2 = hamming_distance(a, m, c, m)
    assert dist2 > 0.5

def test_iris_match_decision():
    a = b"\x00" * 512
    b = b"\x00" * 512
    m = b"\xff" * 512
    res = match_templates(a, m, b, m, threshold=0.32)
    assert res["match"] is True
    assert res["decision"] == "MATCH"
    # Mismatch
    c = b"\xff" * 512
    res2 = match_templates(a, m, c, m, threshold=0.32)
    assert res2["match"] is False
    assert res2["decision"] == "MISMATCH"

def test_iris_no_eye():
    prov = get_provider("rgb")
    img = np.zeros((50, 50, 3), dtype=np.uint8)  # blank, no eye
    res = prov.enroll(img)
    # Should handle gracefully, not raise
    assert "quality" in res

def test_nir_provider_stub():
    prov = get_provider("nir")
    assert prov.name == "NIRProvider"
    res = prov.enroll(np.zeros((100,100,3), dtype=np.uint8))
    assert res["quality"]["usable"] is False
