"""Comprehensive tests for all pipeline modules.

Covers the 6 test scenarios from plan.md Phase 4:
  1. Genuine document + matching face + matching DB → Green
  2. Forged birthdate on physical document vs. DB → Yellow/Red with discrepancy table
  3. Tampered document image (copy-move) → Red/Yellow with ELA heatmap
  4. Imposter face / photo substitution → Red with 3-way face mismatch
  5. Watchlist hit → Red with violet "MOCKED DATA" badge
  6. Sub-second tamper execution assertion (< 1.5s)

Also includes the original 5-module tests and fault isolation checks.

Run:  python -m pytest tests/ -v
"""

from __future__ import annotations

import pathlib
import time

import pytest

from pipeline import deepfake, face_match, liveness, ocr_mrz, tamper
from pipeline import checksums, demographic, watchlist, risk_engine
from pipeline.gemini_scanner import scan_document, simulate_mismatch_scan

SAMPLES = pathlib.Path(__file__).resolve().parent.parent / "samples"
GENUINE = SAMPLES / "genuine_doc.png"
TAMPERED = SAMPLES / "tampered_doc.png"
FACE_A = SAMPLES / "faces" / "person_a.png"
FACE_A2 = SAMPLES / "faces" / "person_a_2.png"
FACE_B = SAMPLES / "faces" / "person_b.png"
BLINK = sorted((SAMPLES / "live").glob("blink_burst_*.png"))
STATIC = sorted((SAMPLES / "live").glob("static_burst_*.png"))

FACES = [FACE_A, FACE_A2, FACE_B]






_KNOWN_MODULE_NAMES = {
    # Pipeline ModuleResult names (pipeline/*/MODULE_NAME).
    "ocr", "tamper", "physical_forgery", "deepfake", "face_match",
    "liveness", "document_quality", "security_zones",
    # Persisted module_results vocab (backend/app.py modules list) —
    # pipeline dict-results + DB rows share the same table.
    "gemini_ai", "watchlist", "checksum", "demographic", "iris",
    "face_quality", "fairness",
}


def assert_contract(result):
    """Every module result must satisfy the shared contract (Schema/DATABASE.md).

    Shape-only: ``module_name`` is a known vocab entry (pipeline + persisted
    DB vocab), ``status`` is ``ok|inconclusive``, ``raw_output`` is a dict,
    and ``score`` is a clipped 0–1 float when ``ok`` (``None`` + ``reason``
    when ``inconclusive``).
    """
    assert isinstance(result.module_name, str) and result.module_name, result
    assert result.module_name in _KNOWN_MODULE_NAMES, (
        f"unknown module_name {result.module_name!r} — extend _KNOWN_MODULE_NAMES"
    )
    assert result.status in {"ok", "inconclusive"}
    assert isinstance(result.raw_output, dict)
    if result.status == "ok":
        assert isinstance(result.score, float)
        assert 0.0 <= result.score <= 1.0
    else:
        assert result.score is None
        assert "reason" in result.raw_output


def test_assets_present():
    for p in [GENUINE, TAMPERED, *FACES, *BLINK, *STATIC]:
        assert p.exists(), f"missing sample asset: {p}"






def test_case_1_genuine_match_modules_ok():
    r_ocr = ocr_mrz.run_ocr_mrz(GENUINE)
    assert_contract(r_ocr)
    assert r_ocr.status == "ok"
    assert r_ocr.raw_output["mrz"]["parsed"] is True


    checks = r_ocr.raw_output["mrz"]["icao_checks"]
    validated = [v for v in checks.values() if isinstance(v, dict) and "ok" in v]
    assert validated, "expected at least one ICAO block to be validated"
    assert all(v["ok"] for v in validated), f"genuine doc failed ICAO: {checks}"

    r_tamper = tamper.run_tamper(GENUINE)
    assert_contract(r_tamper)
    assert r_tamper.status == "ok"
    assert r_tamper.raw_output["tamper_score"] < 0.15, "genuine doc flagged as tampered"

    r_match = face_match.run_face_match(FACE_A, FACE_A2)
    assert_contract(r_match)
    assert r_match.status == "ok"
    assert r_match.raw_output["match"] is True
    assert r_match.raw_output["similarity"] >= 0.55

    r_live = liveness.run_liveness(BLINK)
    assert_contract(r_live)
    assert r_live.status == "ok"
    assert r_live.raw_output["live"] is True
    assert r_live.raw_output["blink_count"] >= 1


def test_case_2_tampered_doc_flagged():

    r_g = tamper.run_tamper(GENUINE)
    r_genuine_score = r_g.raw_output["tamper_score"]

    r = tamper.run_tamper(TAMPERED)
    assert_contract(r)
    assert r.status == "ok"

    assert r.raw_output["tamper_score"] > r_genuine_score, (
        f"tampered ({r.raw_output['tamper_score']}) should exceed genuine ({r_genuine_score})"
    )
    assert r.evidence_uri and pathlib.Path(r.evidence_uri).exists()


def test_case_3_face_mismatch():
    r = face_match.run_face_match(FACE_A, FACE_B)
    assert_contract(r)
    assert r.status == "ok"
    assert r.raw_output["match"] is False
    assert r.raw_output["similarity"] < 0.55
    same = face_match.run_face_match(FACE_A, FACE_A2).raw_output["similarity"]
    assert r.raw_output["similarity"] < same


def test_deepfake_happy_path():
    r = deepfake.run_deepfake(FACE_A)
    assert_contract(r)
    assert r.status == "ok"
    assert "deepfake_score" in r.raw_output
    assert "method" in r.raw_output
    assert 0.0 <= r.raw_output["deepfake_score"] <= 1.0






def test_fault_isolation_bad_path():
    assert_contract(ocr_mrz.run_ocr_mrz("does/not/exist.png"))
    assert_contract(tamper.run_tamper("does/not/exist.png"))
    assert_contract(deepfake.run_deepfake("does/not/exist.png"))
    assert_contract(face_match.run_face_match("does/not/exist.png", "x.png"))
    assert_contract(liveness.run_liveness(["does/not/exist_0.png"]))


def test_fault_isolation_blank_images(tmp_path):
    import numpy as np
    import cv2

    blank = tmp_path / "blank.png"
    cv2.imwrite(str(blank), np.full((320, 320, 3), 200, np.uint8))

    r_ocr = ocr_mrz.run_ocr_mrz(blank)
    assert_contract(r_ocr)

    r = face_match.run_face_match(blank, blank)
    assert_contract(r)
    assert r.status == "inconclusive"

    r = liveness.run_liveness([str(blank)] * 5)
    assert_contract(r)
    assert r.status == "inconclusive"


def test_fault_isolation_empty_burst():
    r = liveness.run_liveness([])
    assert_contract(r)
    assert r.status == "inconclusive"


def test_evidence_images_written():
    fm = face_match.run_face_match(FACE_A, FACE_A2)
    assert fm.evidence_uri and pathlib.Path(fm.evidence_uri).exists()

    tp = tamper.run_tamper(TAMPERED)
    assert tp.evidence_uri and pathlib.Path(tp.evidence_uri).exists()











class TestChecksums:
    """Unit tests for all algorithmic checksum validators."""

    def test_verhoeff_valid_aadhaar(self):
        """Valid Aadhaar numbers should pass Verhoeff."""


        digit = checksums.compute_verhoeff_digit("12345678901")
        full = f"12345678901{digit}"
        assert checksums.validate_verhoeff(full) is True

    def test_verhoeff_invalid_aadhaar(self):
        """Invalid Aadhaar should fail Verhoeff (deterministic vectors)."""
        assert checksums.validate_verhoeff("123456789012") is False
        assert checksums.validate_verhoeff("234569890124") is False

        digit = checksums.compute_verhoeff_digit("12345678901")
        bad_digit = (digit + 1) % 10
        bad_full = f"12345678901{bad_digit}"
        assert checksums.validate_verhoeff(bad_full) is False

    def test_verhoeff_known_valid_vector(self):
        """Independently-generated valid vector (check digit 4)."""
        assert checksums.compute_verhoeff_digit("23456789012") == 4
        assert checksums.validate_verhoeff("234567890124") is True

    def test_verhoeff_with_spaces(self):
        """Aadhaar with spaces/hyphens should still validate."""
        digit = checksums.compute_verhoeff_digit("12345678901")
        full = f"1234 5678 901{digit}"
        assert checksums.validate_verhoeff(full) is True

    def test_verhoeff_wrong_length(self):
        """Non-12-digit strings should fail."""
        assert checksums.validate_verhoeff("123") is False
        assert checksums.validate_verhoeff("") is False
        assert checksums.validate_verhoeff("abcdefghijkl") is False

    def test_pan_valid(self):
        """Valid PAN format should pass."""
        assert checksums.validate_pan_format("ABCPD1234E") is True
        assert checksums.validate_pan_format("ZZZZZ9999Z") is True

    def test_pan_invalid(self):
        """Invalid PAN format should fail."""
        assert checksums.validate_pan_format("1BCPD1234E") is False
        assert checksums.validate_pan_format("ABCPD12345") is False
        assert checksums.validate_pan_format("ABCPD123") is False
        assert checksums.validate_pan_format("") is False

    def test_epic_valid(self):
        """Valid EPIC format should pass."""
        assert checksums.validate_epic_format("ABC1234567") is True
        assert checksums.validate_epic_format("XYZ0000000") is True

    def test_epic_invalid(self):
        """Invalid EPIC format should fail."""
        assert checksums.validate_epic_format("AB12345678") is False
        assert checksums.validate_epic_format("ABCD123456") is False
        assert checksums.validate_epic_format("") is False

    def test_icao_9303_valid_mrz(self):
        """ICAO 9303 validation on correctly-checksummed MRZ lines."""

        doc_num = "AB1234567"
        doc_check = str(checksums.icao_check_digit(doc_num))

        dob = "880412"
        dob_check = str(checksums.icao_check_digit(dob))

        expiry = "280101"
        exp_check = str(checksums.icao_check_digit(expiry))




        line2_parts = (
            doc_num + doc_check
            + "IND"
            + dob + dob_check
            + "M"
            + expiry + exp_check
            + "<" * 14
            + "0"
        )

        line2 = line2_parts.ljust(44, "<")


        composite_block = line2[0:10] + line2[13:20] + line2[21:43]
        comp_check = str(checksums.icao_check_digit(composite_block))
        line2 = line2[:43] + comp_check

        line1 = "P<INDKUMAR<<RAJESH<<<<<<<<<<<<<<<<<<<<<<<<<"[:44]
        result = checksums.validate_icao_9303([line1, line2])

        assert result["document_number"]["ok"] is True
        assert result["date_of_birth"]["ok"] is True
        assert result["date_of_expiry"]["ok"] is True
        assert result["composite"]["ok"] is True

    def test_validate_document_number_dispatch(self):
        """Test the unified dispatch function."""
        digit = checksums.compute_verhoeff_digit("23456789012")
        r = checksums.validate_document_number("aadhaar", f"23456789012{digit}")
        assert r["valid"] is True
        assert r["method"] == "verhoeff_checksum"

        r = checksums.validate_document_number("pan", "ABCPD1234E")
        assert r["valid"] is True

        r = checksums.validate_document_number("voter_id", "ABC1234567")
        assert r["valid"] is True

        r = checksums.validate_document_number("passport", "J8369854")
        assert r["valid"] is None






class TestDemographic:
    """Tests for demographic reconciliation."""

    def test_perfect_match(self):
        extracted = {
            "full_name": "Rajesh Kumar",
            "date_of_birth": "1988-04-12",
            "document_number": "2345 6789 0123",
            "gender": "M",
            "address": "Flat 402, Shanti Vihar, Noida - 201301",
            "father_or_spouse_name": "Ramesh Kumar",
        }
        db_record = {
            "full_name": "Rajesh Kumar",
            "date_of_birth": "1988-04-12",
            "document_number": "234567890123",
            "gender": "M",
            "address": "Flat 402, Shanti Vihar, Sector 15, Noida, UP - 201301",
            "father_or_spouse_name": "Ramesh Kumar",
        }
        result = demographic.reconcile_demographics(extracted, db_record)
        assert result["overall_match"] is True
        assert result["mismatch_count"] == 0

    def test_dob_mismatch_flags_critical(self):
        """Forged birthdate → critical mismatch (plan scenario 2)."""
        extracted = {
            "full_name": "Rajesh Kumar",
            "date_of_birth": "1995-04-12",
            "document_number": "234567890123",
            "gender": "M",
        }
        db_record = {
            "full_name": "Rajesh Kumar",
            "date_of_birth": "1988-04-12",
            "document_number": "234567890123",
            "gender": "M",
        }
        result = demographic.reconcile_demographics(extracted, db_record)
        assert result["overall_match"] is False
        assert "Date of Birth" in result["mismatch_fields"]
        assert "Date of Birth" in result["critical_mismatches"]

    def test_name_fuzzy_match(self):
        """Names with minor differences should still match (token-sort)."""
        extracted = {"full_name": "Kumar Rajesh", "date_of_birth": "1988-04-12",
                     "document_number": "234567890123"}
        db_record = {"full_name": "Rajesh Kumar", "date_of_birth": "1988-04-12",
                     "document_number": "234567890123"}
        result = demographic.reconcile_demographics(extracted, db_record)
        name_comp = [c for c in result["comparisons"] if c["field"] == "Full Name"][0]
        assert name_comp["status"] == "match"

    def test_date_format_normalization(self):
        """Different date formats should still match."""
        extracted = {"full_name": "Test", "date_of_birth": "12/04/1988",
                     "document_number": "123"}
        db_record = {"full_name": "Test", "date_of_birth": "1988-04-12",
                     "document_number": "123"}
        result = demographic.reconcile_demographics(extracted, db_record)
        dob_comp = [c for c in result["comparisons"] if c["field"] == "Date of Birth"][0]
        assert dob_comp["status"] == "match"






class TestWatchlist:
    """Tests for watchlist provider."""

    def test_mock_provider_clear(self):
        """Non-watchlisted person should be clear."""
        result = watchlist.check_watchlist(name="Rajesh Kumar", id_number="234567890123")
        assert result.is_hit is False
        assert result.is_mocked is True
        assert len(result.hits) == 0

    def test_mock_provider_hit_by_name(self):
        """Watchlisted person should be detected by name (plan scenario 5)."""
        result = watchlist.check_watchlist(name="Arjun Veer Rathore")
        assert result.is_hit is True
        assert result.is_mocked is True
        assert len(result.hits) >= 1
        assert "Lookout Circular" in result.hits[0].source

    def test_mock_provider_hit_by_id(self):
        """Watchlisted person should be detected by ID number."""
        result = watchlist.check_watchlist(id_number="BFKPT4567R")
        assert result.is_hit is True
        assert len(result.hits) >= 1

    def test_watchlist_result_serialization(self):
        """WatchlistResult should serialize to dict correctly."""
        result = watchlist.check_watchlist(name="Arjun Veer Rathore")
        d = result.to_dict()
        assert "is_hit" in d
        assert "hits" in d
        assert "is_mocked" in d






class TestRiskEngine:
    """Tests for the composite risk engine."""

    def test_all_clear_green(self):
        """All modules clear → Green verdict (plan scenario 1)."""
        assessment = risk_engine.assess_risk(
            demographic_result={
                "overall_match": True,
                "mismatch_fields": [],
                "critical_mismatches": [],
            },
            tamper_score=0.05,
            deepfake_score=0.1,
            face_similarity=0.92,
            face_match=True,
            liveness_live=True,
            liveness_score=0.8,
            watchlist_hit=False,
        )
        assert assessment.verdict == "Green"
        assert assessment.risk_score < 0.35
        assert len(assessment.flags) == 0

    def test_demographic_mismatch_forces_red(self):
        """Critical demographic mismatch → Red (plan scenario 2)."""
        assessment = risk_engine.assess_risk(
            demographic_result={
                "overall_match": False,
                "mismatch_fields": ["Date of Birth"],
                "critical_mismatches": ["Date of Birth"],
            },
            tamper_score=0.05,
            face_similarity=0.92,
            face_match=True,
            liveness_live=True,
            liveness_score=0.8,
        )
        assert assessment.verdict == "Red"
        assert any("DEMOGRAPHIC" in f for f in assessment.flags)

    def test_tampered_doc_flags_red(self):
        """High tamper score → Red (plan scenario 3)."""
        assessment = risk_engine.assess_risk(
            tamper_score=0.85,
            face_similarity=0.9,
            face_match=True,
        )
        assert assessment.verdict in ("Red", "Yellow")
        assert any("TAMPER" in f for f in assessment.flags)

    def test_face_mismatch_forces_red(self):
        """Face mismatch → Red (plan scenario 4)."""
        assessment = risk_engine.assess_risk(
            face_similarity=0.25,
            face_match=False,
            tamper_score=0.05,
        )
        assert assessment.verdict == "Red"
        assert "FACE_MISMATCH" in assessment.flags

    def test_watchlist_hit_forces_red(self):
        """Watchlist hit → Red (plan scenario 5)."""
        assessment = risk_engine.assess_risk(
            watchlist_hit=True,
            watchlist_result={"is_hit": True, "is_mocked": True},
            face_similarity=0.92,
            face_match=True,
            tamper_score=0.05,
        )
        assert assessment.verdict == "Red"
        assert "WATCHLIST_HIT" in assessment.flags

    def test_liveness_failure_forces_yellow(self):
        """Liveness failure → at least Yellow."""
        assessment = risk_engine.assess_risk(
            liveness_live=False,
            liveness_score=0.1,
            face_similarity=0.92,
            face_match=True,
            tamper_score=0.05,
        )
        assert assessment.verdict in ("Yellow", "Red")
        assert "LIVENESS_FAILURE" in assessment.flags

    def test_inconclusive_module_forces_yellow(self):
        """Any inconclusive module → at least Yellow."""
        assessment = risk_engine.assess_risk(
            tamper_status="inconclusive",
            face_similarity=0.92,
            face_match=True,
        )
        assert assessment.verdict in ("Yellow", "Red")
        assert any("INCONCLUSIVE" in f for f in assessment.flags)

    def test_risk_assessment_serialization(self):
        """RiskAssessment should serialize to dict."""
        assessment = risk_engine.assess_risk(tamper_score=0.5)
        d = assessment.to_dict()
        assert "verdict" in d
        assert "risk_score" in d
        assert "recommendations" in d
        assert "flags" in d






class TestGeminiScanner:
    """Tests for the Gemini AI scanner (offline simulation mode)."""

    @pytest.fixture(autouse=True)
    def _force_offline_gemini(self, monkeypatch):
        """Isolate from any real GEMINI_API_KEY in the developer's .env.

        These tests assert offline-simulation behaviour, so the key must be
        absent regardless of local config (the scanner reads env lazily).
        """
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def test_scan_returns_structured_output(self):
        """Scanner should return complete structured JSON."""
        result = scan_document(str(GENUINE), str(FACE_A))
        assert "document_type" in result
        assert "demographics" in result
        assert "three_way_face_match" in result
        assert "is_simulated" in result
        assert result["is_simulated"] is True

    def test_scan_demographics_populated(self):
        """Demographics should have key fields."""
        result = scan_document(str(GENUINE), str(FACE_A))
        demo = result["demographics"]
        assert "full_name" in demo
        assert "date_of_birth" in demo
        assert "document_number" in demo

    def test_scan_face_match_populated(self):
        """Face match data should be populated."""
        result = scan_document(str(GENUINE), str(FACE_A))
        fm = result["three_way_face_match"]
        assert "live_vs_doc_match" in fm
        assert "similarity_score" in fm
        assert 0.0 <= fm["similarity_score"] <= 1.0

    def test_mismatch_simulation(self):
        """Mismatch simulation should produce low scores."""
        result = simulate_mismatch_scan(str(GENUINE), str(FACE_B))
        assert result["three_way_face_match"]["live_vs_doc_match"] is False
        assert result["three_way_face_match"]["similarity_score"] < 0.5
        assert result["photo_tamper_anomaly"] is True






def _median_of_3(fn):
    """Run fn() 3× and return (median_elapsed, last_result) — flaky-tolerant timing."""
    import statistics

    elapsed = []
    result = None
    for _ in range(3):
        start = time.perf_counter()
        result = fn()
        elapsed.append(time.perf_counter() - start)
    return statistics.median(elapsed), result


def test_tamper_execution_speed():
    """Tamper detection must complete in < 1.5 seconds on CPU (median-of-3)."""
    elapsed, r = _median_of_3(lambda: tamper.run_tamper(GENUINE))
    assert_contract(r)
    assert elapsed < 1.5, f"Tamper median took {elapsed:.2f}s (limit: 1.5s)"


def test_tamper_execution_speed_tampered():
    """Tampered doc analysis must also complete in < 1.5 seconds (median-of-3)."""
    elapsed, r = _median_of_3(lambda: tamper.run_tamper(TAMPERED))
    assert_contract(r)
    assert elapsed < 1.5, f"Tamper median took {elapsed:.2f}s (limit: 1.5s)"


def _clean_base():
    return dict(
        demographic_result={"overall_match": True, "mismatch_fields": [], "critical_mismatches": []},
        tamper_score=0.05,
        face_similarity=0.92,
        face_match=True,
        liveness_live=True,
        liveness_score=0.8,
    )


class TestRiskBoundaries:
    """Threshold-boundary floors (thresholds.json is the single source of truth)."""

    def test_deepfake_at_07_floors_yellow(self):
        a = risk_engine.assess_risk(**_clean_base(), deepfake_score=0.7)
        assert a.verdict in ("Yellow", "Red")
        assert "HIGH_DEEPFAKE_SCORE" in a.flags
        b = risk_engine.assess_risk(**_clean_base(), deepfake_score=0.69)
        assert "HIGH_DEEPFAKE_SCORE" not in b.flags

    def test_deepfake_below_07_no_floor(self):
        a = risk_engine.assess_risk(**_clean_base(), deepfake_score=0.1)
        assert a.verdict == "Green"

    def test_unverified_trust_floors_yellow(self):
        a = risk_engine.assess_risk(
            **_clean_base(),
            registry_trust={"level": "unverified", "verified": False, "reasons": ["missing second-supervisor approval"]},
        )
        assert a.verdict in ("Yellow", "Red")
        assert any("UNVERIFIED_REGISTRY_SOURCE" in f for f in a.flags)

    def test_trust_yellow_floor_needs_demographics(self):
        # Registry trust only applies when a demographic comparison exists.
        a = risk_engine.assess_risk(
            demographic_result=None,
            tamper_score=0.05, face_similarity=0.92, face_match=True,
            registry_trust={"level": "unverified", "verified": False, "reasons": ["x"]},
        )
        assert all("UNVERIFIED" not in f for f in a.flags)

    def test_recapture_document_quality_floors_yellow(self):
        a = risk_engine.assess_risk(
            **_clean_base(),
            document_quality_status="inconclusive",
            document_quality_issues=["blurry"],
        )
        assert a.verdict in ("Yellow", "Red")
        assert any("DOCUMENT_QUALITY_FAILED" in f for f in a.flags)

    def test_tamper_bands(self):
        low = risk_engine.assess_risk(**{**_clean_base(), "tamper_score": 0.39})
        assert not any("TAMPER" in f for f in low.flags)
        mod = risk_engine.assess_risk(**{**_clean_base(), "tamper_score": 0.4})
        assert "MODERATE_TAMPER_SCORE" in mod.flags
        assert mod.verdict in ("Yellow", "Red")
        high = risk_engine.assess_risk(**{**_clean_base(), "tamper_score": 0.7})
        assert "HIGH_TAMPER_SCORE" in high.flags
        assert high.verdict == "Red"

    def test_face_band_low_confidence(self):
        from pipeline.common import load_thresholds

        thr = load_thresholds()
        assert thr["face_low_conf_low"] == 0.45
        assert thr["face_low_conf_high"] == 0.65
        assert thr["face_match"] == 0.55
        for sim in (0.45, 0.55, 0.65):
            a = risk_engine.assess_risk(
                **{**_clean_base(), "face_similarity": sim, "face_match": True}
            )
            assert any("FACE_LOW_CONFIDENCE" in f for f in a.flags), sim
            assert a.verdict in ("Yellow", "Red")
        below = risk_engine.assess_risk(
            **{**_clean_base(), "face_similarity": 0.44, "face_match": True}
        )
        assert not any("FACE_LOW_CONFIDENCE" in f for f in below.flags)
        above = risk_engine.assess_risk(
            **{**_clean_base(), "face_similarity": 0.66, "face_match": True}
        )
        assert not any("FACE_LOW_CONFIDENCE" in f for f in above.flags)

    def test_name_addr_thresholds(self):
        from pipeline.common import load_thresholds

        thr = load_thresholds()
        assert thr["name_match"] == 0.85
        assert thr["address_match"] == 0.60
        # Functional: identical names match; unrelated names mismatch.
        ok = demographic.reconcile_demographics(
            {"full_name": "Rajesh Kumar", "date_of_birth": "1988-04-12", "document_number": "X1"},
            {"full_name": "Rajesh Kumar", "date_of_birth": "1988-04-12", "document_number": "X1"},
        )
        assert [c for c in ok["comparisons"] if c["field"] == "Full Name"][0]["status"] == "match"
        bad = demographic.reconcile_demographics(
            {"full_name": "Arjun Veer Rathore", "date_of_birth": "1988-04-12", "document_number": "X1"},
            {"full_name": "Rajesh Kumar", "date_of_birth": "1988-04-12", "document_number": "X1"},
        )
        assert [c for c in bad["comparisons"] if c["field"] == "Full Name"][0]["status"] == "mismatch"


class TestMissingCoverage:
    """Previously uncovered legs: document_quality gate, fairness ledger,
    Gemini real-cloud parsing, OCR without Tesseract, trust floor."""

    def test_document_quality_gate_failed_shape(self):
        import numpy as np
        from pipeline.document_quality import run_document_quality

        black = np.zeros((600, 800, 3), np.uint8)
        r = run_document_quality(black, save_evidence=False)
        assert r.module_name == "document_quality"
        assert r.status == "inconclusive"
        assert r.score is None
        assert "reason" in r.raw_output
        a = risk_engine.assess_risk(
            **_clean_base(), document_quality_status=r.status,
            document_quality_issues=["too_dark"],
        )
        assert a.verdict in ("Yellow", "Red")

    def test_document_quality_gate_passed(self):
        from pipeline.document_quality import run_document_quality

        r = run_document_quality(str(GENUINE), save_evidence=False)
        assert r.module_name == "document_quality"
        assert r.status in ("ok", "inconclusive")

    def test_fairness_ledger_and_report(self):
        from pipeline.fairness import (
            get_fairness_report, is_low_confidence, log_fairness_case,
        )

        assert is_low_confidence(0.55) is True
        assert is_low_confidence(0.44) is False
        assert is_low_confidence(0.66) is False
        assert is_low_confidence(None) is False
        entry = log_fairness_case(
            9999, {"gender": "M", "date_of_birth": "1990-01-01"},
            0.55, True, low_confidence=True,
        )
        assert entry["low_confidence"] is True
        rep = get_fairness_report(limit=200)
        assert rep["total"] >= 1
        assert "low_confidence_rate" in rep
        assert rep["threshold"] == 0.55
        assert rep["low_conf_band"] == [0.45, 0.65]

    def test_gemini_real_cloud_parsing(self, monkeypatch):
        import pipeline.gemini_scanner as gs

        monkeypatch.setenv("GEMINI_API_KEY", "AIza-valid-test-key-1234567890")
        payload = {
            "document_type": "passport",
            "classification_confidence": 0.99,
            "demographics": {
                "document_number": "L898902C3", "full_name": "Jasmine Specimen",
                "date_of_birth": "1969-12-04", "gender": "F",
                "address": None, "father_or_spouse_name": None,
            },
            "three_way_face_match": {
                "live_vs_doc_match": True, "doc_vs_db_match": None,
                "live_vs_db_match": None, "similarity_score": 0.91,
                "visual_reasoning": "test",
            },
            "photo_tamper_anomaly": False,
        }

        def _fake_call(doc, live, db, timeout, api_key=None, model=None):
            assert api_key and api_key.startswith("AIza")
            return dict(payload)

        monkeypatch.setattr(gs, "_call_gemini", _fake_call)
        out = gs.scan_document(str(GENUINE), str(FACE_A), timeout=5.0)
        assert out["is_simulated"] is False
        assert out["document_type"] == "passport"
        assert out["three_way_face_match"]["similarity_score"] == 0.91
        assert out["model_used"] != "offline_simulation"

    def test_ocr_without_tesseract_degrades(self, monkeypatch):
        import pipeline.ocr_mrz as ocr

        monkeypatch.setattr(ocr, "_tesseract_available", lambda: False)
        r = ocr.run_ocr_mrz(str(GENUINE))
        assert r.module_name == "ocr"
        assert r.status in ("ok", "inconclusive")
        if r.status == "inconclusive":
            assert r.score is None
            assert "reason" in r.raw_output
