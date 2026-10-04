"""Tests for legacy security-zone ROIs (pipeline/security_zones.py).

security_zones is superseded by physical_forgery but still runs in the
pipeline, so its contract matters: every call returns ok/inconclusive with a
bounded score, a `checks` mapping, and never Red-forces on unknown document
types. Asserts below pin shape + bounds (not forensic accuracy — the genuine
specimen itself scores high here, which is why the module is legacy).
"""

import numpy as np
import pytest

from pipeline.security_zones import run_security_zones, TEMPLATE_ZONES


def test_template_zones_exist():
    assert "passport" in TEMPLATE_ZONES
    assert "aadhaar" in TEMPLATE_ZONES
    assert "photo" in TEMPLATE_ZONES["passport"]


def _assert_shape(res):
    assert res.module_name == "security_zones"
    assert res.status in ("ok", "inconclusive")
    assert isinstance(res.raw_output, dict)
    if res.status == "ok":
        assert isinstance(res.score, float)
        assert 0.0 <= res.score <= 1.0
        assert "security_score" in res.raw_output
        assert "checks" in res.raw_output
        assert isinstance(res.raw_output["checks"], dict)
        assert len(res.raw_output["checks"]) >= 1
    else:
        assert res.score is None
        assert "reason" in res.raw_output


def test_security_zones_runs():
    import cv2

    img = np.ones((600, 1000, 3), dtype=np.uint8) * 255
    cv2.circle(img, (180, 300), 50, (0, 0, 0), -1)
    res = run_security_zones(img, document_type="passport", save_evidence=False)
    _assert_shape(res)


def test_security_zones_genuine_shape_and_bounds():
    import cv2

    img = cv2.imread("samples/genuine_doc.png")
    assert img is not None
    res = run_security_zones(img, document_type="passport", save_evidence=False)
    _assert_shape(res)
    if res.status == "ok":
        assert 0.0 <= res.raw_output["security_score"] <= 1.0


def test_security_zones_unknown_type_never_red_forcing():
    img = np.ones((500, 800, 3), dtype=np.uint8) * 200
    res = run_security_zones(img, document_type="unknown", save_evidence=False)
    _assert_shape(res)
    # Unknown templates must degrade gracefully — never raise, never crash.
    assert res.status in ("ok", "inconclusive")


def test_security_zones_never_raises_on_garbage():
    res = run_security_zones("does/not/exist.png", document_type="passport", save_evidence=False)
    _assert_shape(res)
    assert res.status == "inconclusive"
    res = run_security_zones(np.zeros((10, 10, 3), np.uint8), document_type="passport", save_evidence=False)
    _assert_shape(res)


def test_security_zones_risk_mapping():
    from pipeline.risk_engine import assess_risk

    base = dict(
        demographic_result={"overall_match": True, "mismatch_fields": [], "critical_mismatches": []},
        tamper_score=0.05, face_similarity=0.92, face_match=True,
        liveness_live=True, liveness_score=0.8,
    )
    red = assess_risk(**base, security_zones_score=0.8)
    assert red.verdict == "Red"
    assert "HIGH_SECURITY_ZONE_ANOMALY" in red.flags
    yellow = assess_risk(**base, security_zones_score=0.5)
    assert yellow.verdict in ("Yellow", "Red")
    assert "MODERATE_SECURITY_ZONE_ANOMALY" in yellow.flags
