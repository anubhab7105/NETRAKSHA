"""Tests for face-image quality gates (pipeline/face_quality.py + wiring).

Failure modes from the field: poor light, motion blur, tiny/distant faces,
side-angle captures, and extra people in frame must request a RECAPTURE —
never a fabricated match/mismatch. Reference thumbnails (tiny registry
photos) stay exempt so enrolled data keeps verifying.

Run:  python -m pytest tests/test_face_quality.py -v
"""

from __future__ import annotations

import pathlib
import types

import cv2
import numpy as np

from pipeline import face_quality as fq
from pipeline.face_quality import (
    QualityReport,
    assess_capture,
    assess_face,
    brightness_stats,
    combine_reports,
    laplacian_sharpness,
    occlusion_hint,
    yaw_proxy_from_kps,
)


_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SAMPLES = _ROOT / "samples"


def _checkerboard(size: int = 400, squares: int = 8) -> np.ndarray:
    """High-texture synthetic capture (BGR)."""
    tile = size // squares
    board = np.zeros((size, size), np.uint8)
    for y in range(squares):
        for x in range(squares):
            if (x + y) % 2:
                board[y * tile:(y + 1) * tile, x * tile:(x + 1) * tile] = 220
    board += 20
    return cv2.cvtColor(board, cv2.COLOR_GRAY2BGR)


def _flat(value: int = 140, size: int = 400) -> np.ndarray:
    return np.full((size, size, 3), value, np.uint8)


def _face(bbox, kps=None):
    f = types.SimpleNamespace(bbox=np.asarray(bbox, dtype=float), kps=kps)
    return f


def _frontal_kps(cx: float = 200.0, cy: float = 200.0, eye: float = 60.0):
    return np.array([
        [cx - eye / 2, cy - 10], [cx + eye / 2, cy - 10], [cx, cy + 15],
        [cx - 20, cy + 45], [cx + 20, cy + 45],
    ])






def test_sharpness_separates_blur():
    sharp = _checkerboard()
    blurred = cv2.GaussianBlur(sharp, (21, 21), 0)
    g = cv2.cvtColor(sharp, cv2.COLOR_BGR2GRAY)
    gb = cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)
    assert laplacian_sharpness(gb) < laplacian_sharpness(g) / 5


def test_brightness_stats_dark_vs_normal():
    mean_dark, _, _, _ = brightness_stats(np.zeros((100, 100, 3), np.uint8))
    mean_ok, _, _, _ = brightness_stats(_flat(140))
    assert mean_dark < 5
    assert 130 < mean_ok < 150


def test_yaw_proxy_frontal_vs_profile():
    frontal = yaw_proxy_from_kps(_frontal_kps())
    assert frontal is not None and abs(frontal) < 0.05
    side = np.array([[100., 100.], [200., 100.], [190., 130.], [150., 160.], [210., 160.]])
    profile = yaw_proxy_from_kps(side)
    assert profile is not None and abs(profile) > fq.YAW_MAX
    assert yaw_proxy_from_kps(None) is None


def test_occlusion_hint_smoke():
    crop = _checkerboard(200, 8)
    suspected, metrics = occlusion_hint(crop)
    assert isinstance(suspected, bool)
    assert "edge_ratio_lower_upper" in metrics






def test_capture_reference_mode_for_thumbnails():
    rep = assess_capture(np.zeros((96, 96, 3), np.uint8), "live")
    assert rep.reference_mode and rep.passed and not rep.failed


def test_capture_rejects_black_and_white_frames():
    dark = assess_capture(np.zeros((500, 500, 3), np.uint8), "live")
    assert not dark.passed and "too_dark" in dark.failed
    bright = assess_capture(np.full((500, 500, 3), 255, np.uint8), "live")
    assert not bright.passed and "too_bright" in bright.failed


def test_capture_passes_normal_frame():
    rep = assess_capture(_checkerboard(), "live")
    assert rep.passed, rep.failed






def test_face_rejects_blurry_crop():


    live = cv2.imread(str(_SAMPLES / "live" / "blink_burst_05.png"))
    region = live[0:700, 150:850]
    blurred = cv2.GaussianBlur(region, (31, 31), 0)
    face = _face([150, 0, 850, 700], _frontal_kps(500, 300, 250))
    ok_rep = assess_face(live, face, 1, "live", face_crop_bgr=region)
    bad_rep = assess_face(live, face, 1, "live", face_crop_bgr=blurred)
    assert ok_rep.passed, ok_rep.failed
    assert not bad_rep.passed and "blurry" in bad_rep.failed


def test_face_rejects_dark_and_tiny():
    dark_crop = np.full((300, 300, 3), 20, np.uint8)
    rep = assess_face(_flat(), _face([50, 50, 350, 350], _frontal_kps()), 1, "live",
                      face_crop_bgr=dark_crop)
    assert "dark_face" in rep.failed

    img = _flat(size=600)
    rep = assess_face(img, _face([10, 10, 50, 50], _frontal_kps(30, 30, 10)), 1, "live")
    assert "face_too_small" in rep.failed


def test_face_rejects_side_angle_and_live_multiface():
    img = _checkerboard()
    side_kps = np.array([[100., 100.], [200., 100.], [195., 130.], [150., 160.], [210., 160.]])
    rep = assess_face(img, _face([50, 50, 350, 350], side_kps), 1, "live")
    assert "side_angle" in rep.failed

    rep = assess_face(img, _face([50, 50, 350, 350], _frontal_kps()), 2, "live")
    assert "multi_face" in rep.failed


    rep = assess_face(img, _face([50, 50, 350, 350], _frontal_kps()), 2, "document")
    assert rep.passed and "multi_face" in rep.warnings


def test_reference_mode_downgrades_measurement_gates():
    tiny = np.full((96, 96, 3), 140, np.uint8)
    rep = assess_face(tiny, _face([2, 2, 90, 90], _frontal_kps(48, 48, 30)), 1, "live")
    assert not rep.passed
    cap = assess_capture(tiny, "live")
    assert cap.reference_mode


def test_combine_reports_recapture_shape():
    good = QualityReport(role="document", passed=True)
    bad = QualityReport(role="live", passed=False, failed=["blurry", "dark_face"])
    q = combine_reports(good, bad)
    assert q["gate"] == "failed" and q["recapture_requested"] is True
    assert q["recapture_target"] == "live"
    assert len(q["recapture_reasons"]) == 2
    assert all("live capture" in r for r in q["recapture_reasons"])






def test_matcher_requests_recapture_on_blurred_live():
    from pipeline.face_match import run_face_match

    doc = cv2.imread(str(_SAMPLES / "genuine_doc.png"))
    live = cv2.imread(str(_SAMPLES / "live" / "blink_burst_05.png"))
    live_bad = cv2.GaussianBlur(live, (31, 31), 0)
    res = run_face_match(doc, live_bad, save_evidence=False)
    assert res.status == "inconclusive" and res.score is None
    raw = res.raw_output
    assert raw["quality_gate"] == "failed" and raw["recapture_requested"] is True
    assert raw["recapture_target"] == "live"
    assert "reason" in raw


def test_matcher_still_matches_good_pair():
    from pipeline.face_match import run_face_match

    res = run_face_match(str(_SAMPLES / "genuine_doc.png"),
                         str(_SAMPLES / "live" / "blink_burst_05.png"),
                         save_evidence=False)
    assert res.status == "ok" and res.score is not None
    assert res.raw_output.get("quality_gate") == "passed"
    assert res.raw_output.get("recapture_requested") is False
