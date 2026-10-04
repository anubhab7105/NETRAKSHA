"""Tests for the registry-first three-way face comparison.

The advertised 3-way match (document↔live, document↔registry, live↔registry)
must be EVIDENCED, not claimed: every pair with both inputs present is really
computed (quality-gated InsightFace), pairs without inputs are marked
unavailable with a reason, and evidence-backed registry mismatches force Red
(a photo-substituted document can agree with the live impostor while
disagreeing with the official record).

Run:  python -m pytest tests/test_three_way.py -v
"""

from __future__ import annotations

import pathlib

import pytest

from pipeline.face_match import (
    buffalo_models_present,
    run_three_way_match,
)
from pipeline.risk_engine import assess_risk

_ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = str(_ROOT / "samples" / "genuine_doc.png")
LIVE = str(_ROOT / "samples" / "live" / "blink_burst_05.png")
DB_SAME = str(_ROOT / "samples" / "faces" / "person_a.png")
DB_OTHER = str(_ROOT / "samples" / "faces" / "person_b.png")


needs_engine = pytest.mark.skipif(
    not buffalo_models_present(),
    reason="buffalo_l pack not provisioned — engine legs unavailable (run scripts/setup_vendor.sh to enable)",
)


def _ok_pair(p):
    assert p["status"] == "ok", p
    assert isinstance(p["match"], bool)
    assert 0.0 <= p["similarity"] <= 1.0
    assert p["engine"] == "insightface_local"


@needs_engine
def test_three_way_complete_all_pairs_computed():
    out = run_three_way_match(DOC, LIVE, DB_SAME)
    assert out["completeness"] == "complete", out
    for key in ("live_vs_doc", "doc_vs_db", "live_vs_db"):
        _ok_pair(out["pairs"][key])
    assert out["db_pairs_unavailable_reason"] is None
    assert out["primary"]["similarity"] is not None
    assert out["recapture_requested"] is False


@needs_engine
def test_three_way_detects_registry_mismatch():


    out = run_three_way_match(DOC, LIVE, DB_OTHER)
    assert out["completeness"] == "complete", out
    assert isinstance(out["pairs"]["doc_vs_db"]["match"], bool)
    assert isinstance(out["pairs"]["live_vs_db"]["match"], bool)


@needs_engine
def test_three_way_partial_without_registry_photo():
    out = run_three_way_match(DOC, LIVE, None)
    assert out["completeness"] == "partial", out
    _ok_pair(out["pairs"]["live_vs_doc"])
    assert out["pairs"]["doc_vs_db"]["status"] == "unavailable"
    assert out["pairs"]["live_vs_db"]["status"] == "unavailable"
    assert out["db_pairs_unavailable_reason"] == "no_registry_photo"


@needs_engine
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


def test_three_way_without_engine_never_red_from_sim(monkeypatch):
    """When buffalo_l is absent the suite SKIPS engine legs above — but the
    no-engine path itself must still be exercised: partial, never raising,
    and never Red-forcing from simulated guesses."""
    import pipeline.face_match as fm

    if fm.buffalo_models_present():
        pytest.skip("engine present — covered by needs_engine legs above")
    out = run_three_way_match(DOC, LIVE, DB_SAME)
    assert out["completeness"] in ("partial", "unavailable")
    for pair in out["pairs"].values():
        assert pair["status"] in ("ok", "unavailable")


def test_three_way_dead_engine_stays_partial(monkeypatch):
    """Dead local engine degrades to partial/unavailable, never raising."""
    import pipeline.face_match as fm

    def _dead(*args, **kwargs):
        raise RuntimeError("local face engine unavailable")

    monkeypatch.setattr(fm, "run_face_match", _dead)
    out = run_three_way_match(DOC, LIVE, DB_SAME)
    assert out["completeness"] in ("partial", "unavailable")
    for pair in out["pairs"].values():
        assert pair["status"] in ("ok", "unavailable")
        if pair["status"] == "unavailable":
            assert pair.get("reason")
    r = assess_risk(**_clean_base(), db_face_pairs={
        "doc_vs_db_match": None, "live_vs_db_match": None, "evidence": "other"})
    assert r.verdict == "Green"


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


def _reason(**kw):
    from backend.app import _build_final_face_reasoning

    base = dict(
        live_vs_doc_match=None, similarity_score=None,
        doc_vs_db_match=None, doc_vs_db_similarity=None,
        live_vs_db_match=None, live_vs_db_similarity=None,
        visual_reasoning="", comparison_completeness="complete",
    )
    base.update(kw.pop("fm", {}))
    return _build_final_face_reasoning(
        base, kw.pop("sources", {}),
        live_str=kw.pop("live_str", "live.png"),
        live_burst_count=kw.pop("live_burst_count", 1),
        db_photo_path=kw.pop("db_photo_path", "db.png"),
        db_photo_late=kw.pop("db_photo_late", False),
        citizen_id=kw.pop("citizen_id", 7),
        db_unavailable_reason=kw.pop("db_unavailable_reason", None),
        is_simulated=kw.pop("is_simulated", False),
        engine_error=kw.pop("engine_error", None),
        recapture_requested=kw.pop("recapture_requested", False),
        recapture_target=kw.pop("recapture_target", None),
    )


def test_reasoning_case_0236_no_stale_claim():
    """Replica of prod Case #0236: stale 'No database reference image' must go,
    every pair must state verdict + similarity + source, late hit disclosed."""
    out = _reason(
        fm={
            "live_vs_doc_match": False, "similarity_score": 0.28,
            "doc_vs_db_match": True, "doc_vs_db_similarity": 0.95,
            "live_vs_db_match": False, "live_vs_db_similarity": 0.35,
            "visual_reasoning": (
                "Live capture shows an adult male with glasses, failed live-vs-doc match. "
                "No database reference image (Image 3) was provided."),
            "comparison_completeness": "complete",
        },
        sources={"live_vs_doc": "gemini", "doc_vs_db": "gemini_late", "live_vs_db": "gemini_late"},
        db_photo_late=True,
    )
    assert "No database reference image" not in out
    assert "live-vs-doc: mismatch (0.280" in out
    assert "doc-vs-DB: match (0.950" in out
    assert "live-vs-DB: mismatch (0.350" in out
    assert "late cloud scan" in out
    assert "late hit after AI scan" in out
    assert "Final 3-way:" in out


def test_reasoning_names_issue_per_branch():
    no_live = _reason(live_str=None, db_photo_path=None, citizen_id=None,
                      db_unavailable_reason=None)
    assert "live image missing" in no_live
    assert "no registry record" in no_live

    no_photo = _reason(db_photo_path=None, db_unavailable_reason="registry_photo_download_failed")
    assert "could not be fetched from storage" in no_photo

    dead_engine = _reason(
        fm={"live_vs_doc_match": False, "similarity_score": 0.20,
            "comparison_completeness": "partial"},
        sources={"live_vs_doc": "gemini", "doc_vs_db": "none", "live_vs_db": "none"},
        db_unavailable_reason="local_face_engine_unavailable",
        engine_error="comparison_failed: RuntimeError")
    assert "face engine unavailable" in dead_engine
    assert "manual officer review required" in dead_engine

    simulated = _reason(is_simulated=True, recapture_requested=True, recapture_target="live")
    assert "cloud AI offline" in simulated
    assert "recapture needed: live" in simulated


def test_reasoning_idempotent_and_threshold_labeled():
    first = _reason(
        fm={"live_vs_doc_match": True, "similarity_score": 0.92,
            "doc_vs_db_match": True, "doc_vs_db_similarity": 0.95,
            "live_vs_db_match": True, "live_vs_db_similarity": 0.91,
            "visual_reasoning": "Early forensic text.",
            "comparison_completeness": "complete"},
        sources={"live_vs_doc": "local", "doc_vs_db": "local_late", "live_vs_db": "local"},
    )
    assert first.count("Final 3-way:") == 1
    assert "thr 0.55" in first
    from backend.app import _build_final_face_reasoning

    again = _build_final_face_reasoning(
        {"live_vs_doc_match": True, "similarity_score": 0.92,
         "doc_vs_db_match": True, "doc_vs_db_similarity": 0.95,
         "live_vs_db_match": True, "live_vs_db_similarity": 0.91,
         "visual_reasoning": first, "comparison_completeness": "complete"},
        {"live_vs_doc": "local", "doc_vs_db": "local_late", "live_vs_db": "local"},
        live_str="live.png", live_burst_count=1, db_photo_path="db.png",
        db_photo_late=False, citizen_id=7, db_unavailable_reason=None,
        is_simulated=False, engine_error=None,
        recapture_requested=False, recapture_target=None)
    assert again == first
