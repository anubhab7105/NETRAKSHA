"""Tests for security zones."""

import numpy as np
from pipeline.security_zones import run_security_zones, TEMPLATE_ZONES

def test_template_zones_exist():
    assert "passport" in TEMPLATE_ZONES
    assert "aadhaar" in TEMPLATE_ZONES
    assert "photo" in TEMPLATE_ZONES["passport"]

def test_security_zones_runs():
    # Create a dummy document image
    img = np.ones((600, 1000, 3), dtype=np.uint8) * 255
    # Add a fake face in photo zone for passport
    import cv2
    cv2.circle(img, (180, 300), 50, (0,0,0), -1)
    res = run_security_zones(img, document_type="passport", save_evidence=False)
    assert res.status in ("ok", "inconclusive")
    assert "security_score" in res.raw_output
    assert "checks" in res.raw_output

def test_security_zones_unknown_type():
    img = np.ones((500, 800, 3), dtype=np.uint8) * 200
    res = run_security_zones(img, document_type="unknown", save_evidence=False)
    assert res.status in ("ok", "inconclusive")
