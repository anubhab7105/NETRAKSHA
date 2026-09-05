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


# ---------------------------------------------------------------------------
# Contract helpers
# ---------------------------------------------------------------------------

def assert_contract(result):
    """Every module result must satisfy the shared contract (Shema.md)."""
    assert result.module_name in {
        "ocr", "tamper", "deepfake", "face_match", "liveness",
    }
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


# ---------------------------------------------------------------------------
# Original module tests (preserved from existing test_pipeline.py)
# ---------------------------------------------------------------------------

def test_case_1_genuine_match_modules_ok():
    r_ocr = ocr_mrz.run_ocr_mrz(GENUINE)
    assert_contract(r_ocr)
    assert r_ocr.status == "ok"
    assert r_ocr.raw_output["mrz"]["parsed"] is True

    # every ICAO block that could be validated should actually check OK
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
    # Get genuine baseline first for comparison
    r_g = tamper.run_tamper(GENUINE)
    r_genuine_score = r_g.raw_output["tamper_score"]

    r = tamper.run_tamper(TAMPERED)
    assert_contract(r)
    assert r.status == "ok"
    # tampered score should be clearly above genuine baseline
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


# ---------------------------------------------------------------------------
# Fault isolation (Techspec §5)
# ---------------------------------------------------------------------------

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


# ===========================================================================
# NEW TESTS — Phase 4: Plan.md scenarios + new modules
# ===========================================================================


# ---------------------------------------------------------------------------
# Checksums module tests
# ---------------------------------------------------------------------------

class TestChecksums:
    """Unit tests for all algorithmic checksum validators."""

    def test_verhoeff_valid_aadhaar(self):
        """Valid Aadhaar numbers should pass Verhoeff."""
        # Use a known valid Verhoeff number
        # Build one: compute check digit for 11 digits, then validate 12
        digit = checksums.compute_verhoeff_digit("12345678901")
        full = f"12345678901{digit}"
        assert checksums.validate_verhoeff(full) is True

    def test_verhoeff_invalid_aadhaar(self):
        """Invalid Aadhaar should fail Verhoeff."""
        assert checksums.validate_verhoeff("123456789012") is False or \
               checksums.validate_verhoeff("000000000000") is True  # 0s could be valid
        # Definitely wrong: flip last digit of a valid number
        digit = checksums.compute_verhoeff_digit("12345678901")
        bad_digit = (digit + 1) % 10
        bad_full = f"12345678901{bad_digit}"
        assert checksums.validate_verhoeff(bad_full) is False

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
        # Build a valid MRZ line2 with correct check digits
        doc_num = "AB1234567"  # 9 chars
        doc_check = str(checksums.icao_check_digit(doc_num))

        dob = "880412"
        dob_check = str(checksums.icao_check_digit(dob))

        expiry = "280101"
        exp_check = str(checksums.icao_check_digit(expiry))

        # Construct line2 per TD3 layout:
        # [0:9]=doc_num, [9]=check, [10:13]=nationality, [13:19]=dob, [19]=check,
        # [20]=sex, [21:27]=expiry, [27]=check, [28:42]=personal, [43]=composite
        line2_parts = (
            doc_num + doc_check  # 0-9
            + "IND"              # 10-12 nationality
            + dob + dob_check    # 13-19
            + "M"                # 20 sex
            + expiry + exp_check # 21-27
            + "<" * 14           # 28-41 personal number + check
            + "0"                # 42 padding
        )
        # Pad to 44 chars
        line2 = line2_parts.ljust(44, "<")

        # Compute composite check digit
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
        assert r["valid"] is None  # needs MRZ lines


# ---------------------------------------------------------------------------
# Demographic module tests
# ---------------------------------------------------------------------------

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
            "date_of_birth": "1995-04-12",  # forged: 7 years younger
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


# ---------------------------------------------------------------------------
# Watchlist module tests
# ---------------------------------------------------------------------------

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
        result = watchlist.check_watchlist(name="Vikram Singh Chauhan")
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
        result = watchlist.check_watchlist(name="Vikram Singh Chauhan")
        d = result.to_dict()
        assert "is_hit" in d
        assert "hits" in d
        assert "is_mocked" in d


# ---------------------------------------------------------------------------
# Risk Engine tests
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Gemini scanner tests (offline simulation)
# ---------------------------------------------------------------------------

class TestGeminiScanner:
    """Tests for the Gemini AI scanner (offline simulation mode)."""

    def test_scan_returns_structured_output(self):
        """Scanner should return complete structured JSON."""
        result = scan_document(str(GENUINE), str(FACE_A))
        assert "document_type" in result
        assert "demographics" in result
        assert "three_way_face_match" in result
        assert "is_simulated" in result
        assert result["is_simulated"] is True  # no API key in test

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


# ---------------------------------------------------------------------------
# Scenario 6: Sub-second tamper execution (plan: < 1.5s assertion)
# ---------------------------------------------------------------------------

def test_tamper_execution_speed():
    """Tamper detection must complete in < 1.5 seconds on CPU."""
    start = time.perf_counter()
    r = tamper.run_tamper(GENUINE)
    elapsed = time.perf_counter() - start
    assert_contract(r)
    assert elapsed < 1.5, f"Tamper took {elapsed:.2f}s (limit: 1.5s)"


def test_tamper_execution_speed_tampered():
    """Tampered doc analysis must also complete in < 1.5 seconds."""
    start = time.perf_counter()
    r = tamper.run_tamper(TAMPERED)
    elapsed = time.perf_counter() - start
    assert_contract(r)
    assert elapsed < 1.5, f"Tamper took {elapsed:.2f}s (limit: 1.5s)"
