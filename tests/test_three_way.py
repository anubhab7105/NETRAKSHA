
from __future__ import annotations

from pipeline.face_match import run_three_way_match
from pipeline.risk_engine import assess_risk

DOC = "samples/genuine_doc.png"
LIVE = "samples/live/blink_burst_05.png"
DB_SAME = "samples/faces/person_a.png"
DB_OTHER = "samples/faces/person_b.png"


def _ok_pair(p):
    assert p["status"] == "ok", p
    assert isinstance(p["match"], bool)
    assert 0.0 <= p["similarity"] <= 1.0
    assert p["engine"] == "insightface_local"


def test_three_way_complete_all_pairs_computed():
    out = run_three_way_match(DOC, LIVE, DB_SAME)
    assert out["completeness"] == "complete", out
    for key in ("live_vs_doc", "doc_vs_db", "live_vs_db"):
        _ok_pair(out["pairs"][key])
    assert out["db_pairs_unavailable_reason"] is None
    assert out["primary"]["similarity"] is not None
    assert out["recapture_requested"] is False


def test_three_way_detects_registry_mismatch():


    out = run_three_way_match(DOC, LIVE, DB_OTHER)
    assert out["completeness"] == "complete", out
    assert isinstance(out["pairs"]["doc_vs_db"]["match"], bool)
    assert isinstance(out["pairs"]["live_vs_db"]["match"], bool)


def test_three_way_partial_without_registry_photo():
    out = run_three_way_match(DOC, LIVE, None)
    assert out["completeness"] == "partial", out
    _ok_pair(out["pairs"]["live_vs_doc"])
    assert out["pairs"]["doc_vs_db"]["status"] == "unavailable"
    assert out["pairs"]["live_vs_db"]["status"] == "unavailable"
    assert out["db_pairs_unavailable_reason"] == "no_registry_photo"


def test_three_way_partial_without_live_capture():
    out = run_three_way_match(DOC, None, DB_SAME)
    assert out["completeness"] == "partial", out
    assert out["pairs"]["live_vs_doc"]["status"] == "unavailable"
    assert out["pairs"]["live_vs_db"]["status"] == "unavailable"
    _ok_pair(out["pairs"]["doc_vs_db"])
    assert out["recapture_requested"] is False


def test_three_way_unavailable_without_inputs():
    out = run_three_way_match(DOC, None, None)
    assert out["completeness"] in ("partial", "unavailable")
    assert out["db_pairs_unavailable_reason"] is not None


def test_three_way_never_raises_on_garbage():
    out = run_three_way_match("does/not/exist.png", None, "also/missing.png")
    assert out["completeness"] == "unavailable"
    assert out["primary"] == {"similarity": None, "match": None}






def _clean_base():
    return dict(
        demographic_result={"overall_match": True, "mismatch_fields": [], "critical_mismatches": []},
        tamper_score=0.05,
        face_similarity=0.92,
        face_match=True,
        liveness_live=True,
        liveness_score=0.8,
    )


def test_risk_red_on_local_registry_mismatch():
    r = assess_risk(**_clean_base(), db_face_pairs={
        "doc_vs_db_match": False, "live_vs_db_match": True, "evidence": "local"})
    assert r.verdict == "Red"
    assert "DOC_DB_FACE_MISMATCH" in r.flags

    r = assess_risk(**_clean_base(), db_face_pairs={
        "doc_vs_db_match": True, "live_vs_db_match": False, "evidence": "local"})
    assert r.verdict == "Red"
    assert "LIVE_DB_FACE_MISMATCH" in r.flags


def test_risk_ignores_nonlocal_registry_claims():
    for evidence in ("gemini", "simulated", None):
        r = assess_risk(**_clean_base(), db_face_pairs={
            "doc_vs_db_match": False, "live_vs_db_match": False, "evidence": evidence})
        assert r.verdict == "Green", (evidence, r.flags)

    r = assess_risk(**_clean_base(), db_face_pairs={
        "doc_vs_db_match": None, "live_vs_db_match": None, "evidence": "local"})
    assert r.verdict == "Green"
    r = assess_risk(**_clean_base())
    assert r.verdict == "Green"
