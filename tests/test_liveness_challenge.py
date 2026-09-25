"""Tests for active liveness challenges."""

import pytest
from pipeline.liveness import CHALLENGE_TYPES, HEAD_YAW_THRESHOLD, MOUTH_OPEN_THRESHOLD

def test_challenge_types():
    assert "blink" in CHALLENGE_TYPES
    assert "head_turn" in CHALLENGE_TYPES
    assert "mouth_open" in CHALLENGE_TYPES

def test_liveness_default_is_blink():
    from pipeline.liveness import run_liveness
    import numpy as np

    img = np.zeros((100,100,3), dtype=np.uint8)
    res = run_liveness([img])
    assert res.status == "inconclusive"

def test_liveness_challenge_param():
    from pipeline.liveness import run_liveness
    import numpy as np

    img = np.zeros((100,100,3), dtype=np.uint8)
    for challenge in CHALLENGE_TYPES:
        res = run_liveness([img]*4, challenge_type=challenge)
        assert res.status in ("ok", "inconclusive")
