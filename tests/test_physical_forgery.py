"""Tests for physical forgery detection (pipeline/physical_forgery.py).

ELA + copy-move miss whole forgery classes (re-typeset MRZ, swapped
portraits, screen recaptures, broken layouts). Each test forges the genuine
specimen accordingly and asserts the RIGHT sub-check fires — while the
genuine specimen stays clean with margin.

Run:  python -m pytest tests/test_physical_forgery.py -v
"""

from __future__ import annotations

import os
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pipeline.physical_forgery import run_physical_forgery
from pipeline.risk_engine import assess_risk

GENUINE = "samples/genuine_doc.png"
TAMPERED = "samples/tampered_doc.png"


def _prop_font(size: int):
    for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "C:/Windows/Fonts/arial.ttf"):
        if os.path.exists(cand):
            return ImageFont.truetype(cand, size)
    return ImageFont.load_default(size=size)


def _photo_swap() -> np.ndarray:
    base = cv2.imread(GENUINE)
    face = cv2.resize(cv2.imread("samples/faces/person_b.png"), (260, 240))
    out = base.copy()
    out[80:320, 690:950] = face
    return out


def _mrz_retype() -> np.ndarray:
    base = cv2.imread(GENUINE)
    pil = Image.fromarray(cv2.cvtColor(base, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(pil)
    d.rectangle([28, 494, 975, 540], fill=(255, 255, 255))
    d.text((30, 496), "P<UTOSPECIMEN<<JASMINE<<<<<<<<<<<<<<<<<<<<<",
           font=_prop_font(40), fill=(5, 5, 5))
    return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)


def _screen_moire() -> np.ndarray:
    base = cv2.imread(GENUINE).astype(np.float32)
    yy, xx = np.mgrid[0:700, 0:1000]
    grid = (14 * np.sin(2 * np.pi * xx / 5.0) + 14 * np.sin(2 * np.pi * yy / 5.0))[:, :, None]
    return np.clip(base + grid, 0, 255).astype(np.uint8)


def _mrz_removed() -> np.ndarray:
    out = cv2.imread(GENUINE).copy()
    out[478:700, :] = 245
    return out


def _run(img, **kw):
    kw.setdefault("document_type_hint", "passport")
    kw.setdefault("doc_number_hint", "L898902C3")
    return run_physical_forgery(img, save_evidence=False, **kw)


def assert_contract(result):
    assert result.module_name == "physical_forgery"
    assert result.status in {"ok", "inconclusive"}
    assert isinstance(result.raw_output, dict)
    if result.status == "ok":
        assert isinstance(result.score, float)
        assert 0.0 <= result.score <= 1.0
        assert "physical_score" in result.raw_output
        assert "checks" in result.raw_output
    else:
        assert result.score is None
        assert "reason" in result.raw_output


def test_genuine_clean_with_margin():
    r = _run(cv2.imread(GENUINE))
    assert_contract(r)
    assert r.status == "ok"
    assert r.score < 0.25, f"genuine scores {r.score} — too close to Yellow (0.4)"
    assert r.raw_output.get("checks_fired") == []
    assert len(r.raw_output.get("checks_available", [])) >= 4


def test_tampered_specimen_runs_layout_fires():
    r = _run(cv2.imread(TAMPERED))
    assert_contract(r)
    assert r.status == "ok"


    assert "layout" in r.raw_output.get("checks_fired", [])


def test_photo_swap_fires_photo_boundary():
    r = _run(_photo_swap())
    assert_contract(r)
    assert r.status == "ok"
    assert "photo_boundary" in r.raw_output.get("checks_fired", [])
    assert r.score > _run(cv2.imread(GENUINE)).score


def test_mrz_retype_fires_font_consistency():
    r = _run(_mrz_retype())
    assert_contract(r)
    assert r.status == "ok"
    assert "font_consistency" in r.raw_output.get("checks_fired", [])
    assert r.score > _run(cv2.imread(GENUINE)).score


def test_screen_recapture_fires_print_scan():
    r = _run(_screen_moire())
    assert_contract(r)
    assert r.status == "ok"
    assert "print_scan" in r.raw_output.get("checks_fired", [])
    assert r.score > _run(cv2.imread(GENUINE)).score


def test_missing_mrz_fires_layout():
    r = _run(_mrz_removed())
    assert_contract(r)
    assert r.status == "ok"
    assert "layout" in r.raw_output.get("checks_fired", [])


def test_qr_absent_is_not_available_not_suspicious():
    r = _run(cv2.imread(GENUINE))
    qr = r.raw_output["checks"]["qr_barcode"]
    assert qr["status"] == "not_available"
    assert qr["score"] == 0.0


def test_hologram_never_scored():
    r = _run(cv2.imread(GENUINE))
    sec = r.raw_output["checks"]["security_features"]
    assert "not_verifiable_single_image" in sec["details"].get("hologram", "")


def test_garbage_is_inconclusive():
    assert_contract(run_physical_forgery("does/not/exist.png", save_evidence=False))
    r = run_physical_forgery(np.zeros((10, 10, 3), np.uint8), save_evidence=False)
    assert_contract(r)
    assert r.status == "inconclusive"


def test_evidence_image_written(tmp_path):
    import pipeline.common as common

    old = common.EVIDENCE_DIR
    common.EVIDENCE_DIR = tmp_path
    try:
        r = run_physical_forgery(GENUINE, document_type_hint="passport")
        assert_contract(r)
        assert r.evidence_uri and os.path.exists(r.evidence_uri)
    finally:
        common.EVIDENCE_DIR = old


def test_module_fast_enough():
    import statistics

    img = cv2.imread(GENUINE)
    elapsed = []
    r = None
    for _ in range(3):
        start = time.perf_counter()
        r = _run(img)
        elapsed.append(time.perf_counter() - start)
    median = statistics.median(elapsed)
    assert_contract(r)
    assert median < 5.0, f"physical forgery median took {median:.2f}s"






def _clean_base():
    return dict(
        demographic_result={"overall_match": True, "mismatch_fields": [], "critical_mismatches": []},
        tamper_score=0.05,
        face_similarity=0.92,
        face_match=True,
        liveness_live=True,
        liveness_score=0.8,
    )


def test_risk_red_on_high_physical_score():
    r = assess_risk(**_clean_base(), physical_score=0.85, physical_status="ok")
    assert r.verdict == "Red"
    assert "HIGH_PHYSICAL_FORGERY_SCORE" in r.flags


def test_risk_yellow_on_moderate_physical_score():
    r = assess_risk(**_clean_base(), physical_score=0.5, physical_status="ok")
    assert r.verdict == "Yellow"
    assert "MODERATE_PHYSICAL_FORGERY_SCORE" in r.flags


def test_risk_yellow_on_physical_inconclusive():
    r = assess_risk(**_clean_base(), physical_score=None, physical_status="inconclusive")
    assert r.verdict in ("Yellow", "Red")
    assert "PHYSICAL_FORGERY_INCONCLUSIVE" in r.flags


def test_risk_ignores_clean_physical_score():
    r = assess_risk(**_clean_base(), physical_score=0.03, physical_status="ok")
    assert r.verdict == "Green"
    assert not any("PHYSICAL" in f for f in r.flags)
