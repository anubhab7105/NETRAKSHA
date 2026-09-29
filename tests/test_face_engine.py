
from __future__ import annotations


def test_engine_status_shape_without_download():
    from pipeline import face_match

    st = face_match.local_engine_status()
    assert set(st) == {"initialised", "models_present", "provider", "last_error"}
    assert isinstance(st["models_present"], bool)
    assert st["provider"] is None or isinstance(st["provider"], str)
    assert st["last_error"] is None or isinstance(st["last_error"], str)


def test_prewarm_returns_bool_and_status_consistent():
    from pipeline import face_match

    ok = face_match.prewarm_local_engine()
    assert isinstance(ok, bool)
    if face_match.buffalo_models_present():
        assert ok is True
        st = face_match.local_engine_status()
        assert st["initialised"] is True
        assert st["last_error"] is None


def test_late_gemini_gate_matrix():
    import backend.app as app

    full = {"doc_vs_db_match": True, "live_vs_db_match": True}
    assert app._needs_late_gemini_face(False, "live.png", "/db.png", {}) is True
    assert app._needs_late_gemini_face(False, None, "/db.png", {}) is True
    assert app._needs_late_gemini_face(False, "live.png", "/db.png", full) is False

    assert app._needs_late_gemini_face(
        False, "live.png", "/db.png", {"doc_vs_db_match": True}) is True

    assert app._needs_late_gemini_face(True, "live.png", "/db.png", {}) is False

    assert app._needs_late_gemini_face(False, "live.png", None, {}) is False
    assert app._needs_late_gemini_face(False, "live.png", "", {}) is False
