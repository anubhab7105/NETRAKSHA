import pytest
from backend.pdf_report import generate_case_pdf

def test_generate_pdf_minimal():
    case = {
        "id": 1,
        "verdict": "Green",
        "risk_score": 10.0,
        "document_type": "passport",
        "status": "cleared",
        "unit": "BORDER_UNIT_1",
        "officer_id": 101,
    }
    pdf_bytes = generate_case_pdf(case_data=case, extracted_fields=[], module_results=[])
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1000

def test_generate_pdf_full():
    case = {
        "id": 42,
        "verdict": "Red",
        "risk_score": 85.0,
        "document_type": "passport",
        "status": "escalated",
        "unit": "BORDER_UNIT_1",
        "officer_id": 102,
    }
    fields = [
        {
            "field_name": "full_name",
            "extracted_value": "Rajesh Kumar",
            "expected_value": "Rajesh Kumar",
            "match_status": "match",
        },
        {
            "field_name": "dob",
            "extracted_value": "14/08/1988",
            "expected_value": "14/08/1982",
            "match_status": "mismatch",
        },
    ]
    modules = [
        {"module_name": "tamper", "score": 0.82, "status": "ok", "raw_output": {"details": "splicing detected"}},
        {"module_name": "face_match", "score": 0.45, "status": "ok", "raw_output": {"live_vs_doc_match": False}},
        {"module_name": "watchlist", "score": 0.0, "status": "ok", "raw_output": {"is_hit": False}},
    ]
    citizen = {"name": "Rajesh Kumar", "dob": "14/08/1982"}
    provenance = {"audit_chain_hash": "a1b2c3d4e5f67890abcdef1234567890"}

    pdf_bytes = generate_case_pdf(
        case_data=case,
        extracted_fields=fields,
        module_results=modules,
        citizen_data=citizen,
        provenance_data=provenance,
    )
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 2000

def test_generate_pdf_handles_none_gracefully():
    case = {"id": 99}
    pdf_bytes = generate_case_pdf(
        case_data=case,
        extracted_fields=None or [],
        module_results=None or [],
        citizen_data=None,
        provenance_data=None,
    )
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1000
