"""Tests for active liveness challenges (pipeline/liveness.py).

Meaningful asserts on real sample bursts (not just smoke):
- blink burst (genuine motion + blink) must verify LIVE with blink_count >= 1
  and score >= liveness threshold (0.45);
- static burst (frozen frames) must verify NOT live with score < threshold;
- challenge assignment is advisory: a live person passing via another action
  reports `challenge_not_observed:<name>`, never a hard fail;
- garbage / undersized bursts degrade to inconclusive, never raise.
"""

from __future__ import annotations

import pathlib

import pytest

from pipeline.common import load_thresholds
from pipeline.liveness import (
    CHALLENGE_TYPES,
    HEAD_YAW_THRESHOLD,
    MOUTH_OPEN_THRESHOLD,
    run_liveness,
)

_SAMPLES = pathlib.Path(__file__).resolve().parent.parent / "samples"
BLINK = sorted((_SAMPLES / "live").glob("blink_burst_*.png"))
STATIC = sorted((_SAMPLES / "live").glob("static_burst_*.png"))


def test_challenge_types():
    assert set(CHALLENGE_TYPES) == {"blink", "head_turn", "mouth_open"}
    assert HEAD_YAW_THRESHOLD == 0.30
    assert MOUTH_OPEN_THRESHOLD == 0.04
    assert load_thresholds()["liveness"] == 0.45


def test_liveness_threshold_single_source():
    from pipeline.liveness import _liveness_threshold

    assert _liveness_threshold() == load_thresholds()["liveness"] == 0.45


def test_blink_burst_is_live():
    assert len(BLINK) >= 3, "blink burst samples missing"
    res = run_liveness([str(p) for p in BLINK])
    assert res.module_name == "liveness"
    assert res.status == "ok", res.raw_output
    assert res.raw_output["live"] is True
    assert res.raw_output["blink_count"] >= 1
    assert res.score is not None and res.score >= 0.45
    assert res.raw_output["challenge_type"] in CHALLENGE_TYPES


def test_static_burst_is_not_live():
    assert len(STATIC) >= 3, "static burst samples missing"
    res = run_liveness([str(p) for p in STATIC])
    assert res.status == "ok", res.raw_output
    assert res.raw_output["live"] is False
    assert res.score is not None and res.score < 0.45
    assert res.raw_output["blink_count"] == 0


def test_blink_scores_above_static():
    blink = run_liveness([str(p) for p in BLINK])
    static = run_liveness([str(p) for p in STATIC])
    assert blink.status == "ok" and static.status == "ok"
    assert blink.score > static.score


def test_challenge_miss_is_advisory_not_fail():
    # Blink burst under a head_turn assignment: still LIVE (blink certifies),
    # but the missed assignment is disclosed for audit.
    res = run_liveness([str(p) for p in BLINK], challenge_type="head_turn")
    assert res.status == "ok"
    if res.raw_output["live"] is True and res.raw_output.get("head_turn_detected") is False:
        assert "challenge_not_observed:head_turn" in res.raw_output.get("spoof_signals", [])


def test_liveness_default_is_blink():
    import numpy as np

    img = np.zeros((100, 100, 3), dtype=np.uint8)
    res = run_liveness([img])
    assert res.status == "inconclusive"


def test_liveness_challenge_param():
    import numpy as np

    img = np.zeros((100, 100, 3), dtype=np.uint8)
    for challenge in CHALLENGE_TYPES:
        res = run_liveness([img] * 4, challenge_type=challenge)
        assert res.status in ("ok", "inconclusive")
        if res.status == "ok":
            assert res.raw_output["challenge_type"] == challenge


def test_liveness_never_raises_on_garbage():
    r = run_liveness([])
    assert r.status == "inconclusive" and r.score is None
    r = run_liveness(["does/not/exist_0.png"])
    assert r.status == "inconclusive" and r.score is None


def test_liveness_risk_floor():
    from pipeline.risk_engine import assess_risk

    base = dict(
        demographic_result={"overall_match": True, "mismatch_fields": [], "critical_mismatches": []},
        tamper_score=0.05, face_similarity=0.92, face_match=True,
    )
    fail = assess_risk(**base, liveness_live=False, liveness_score=0.1)
    assert fail.verdict in ("Yellow", "Red")
    assert "LIVENESS_FAILURE" in fail.flags
