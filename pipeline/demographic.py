"""Demographic database reconciliation module.

Compares AI-extracted demographics against official citizen registry records.
Produces a structured comparison list with per-field match/mismatch status
and an overall parity assessment.

Key features:
  * Name parity:  Token-sort fuzzy string distance (tolerance >= 0.85)
  * DOB parity:   Strict date comparison (flags forged birthdates)
  * Address parity: Locality, state, and PIN code checks
  * Document ID parity: Exact match after normalization
"""

from __future__ import annotations

import re
from typing import Any, Optional


def _normalize(value: Optional[str]) -> str:
    """Normalize a string for comparison: lowercase, strip, collapse whitespace."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _normalize_date(date_str: Optional[str]) -> str:
    """Normalize a date string to YYYY-MM-DD format for comparison.

    Handles common Indian date formats:
      - YYYY-MM-DD
      - DD/MM/YYYY
      - DD-MM-YYYY
      - DD.MM.YYYY
    """
    if not date_str:
        return ""
    s = str(date_str).strip()

    # Already YYYY-MM-DD
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$", s)
    if m:
        return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"

    return _normalize(s)


def _normalize_doc_number(number: Optional[str]) -> str:
    """Normalize a document number: uppercase, strip spaces/hyphens."""
    if not number:
        return ""
    return re.sub(r"[\s\-]", "", str(number).strip().upper())


def _token_sort_similarity(a: str, b: str) -> float:
    """Compute a token-sort fuzzy similarity between two strings.

    Uses a simplified Levenshtein-based approach:
    1. Tokenize and sort both strings
    2. Compute character-level similarity
    Returns 0.0 to 1.0 (1.0 = exact match).
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0

    # Token-sort: split, sort alphabetically, rejoin
    tokens_a = " ".join(sorted(a.lower().split()))
    tokens_b = " ".join(sorted(b.lower().split()))

    if tokens_a == tokens_b:
        return 1.0

    # Levenshtein distance
    dist = _levenshtein(tokens_a, tokens_b)
    max_len = max(len(tokens_a), len(tokens_b))
    return round(1.0 - (dist / max_len), 4) if max_len > 0 else 1.0


def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)

    if len(s2) == 0:
        return len(s1)

    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr.append(min(
                curr[j] + 1,       # insert
                prev[j + 1] + 1,   # delete
                prev[j] + cost,    # substitute
            ))
        prev = curr
    return prev[-1]


def _extract_pin_code(address: Optional[str]) -> Optional[str]:
    """Extract a 6-digit Indian PIN code from an address string."""
    if not address:
        return None
    m = re.search(r"\b(\d{6})\b", address)
    return m.group(1) if m else None


def reconcile_demographics(extracted: dict, db_record: dict) -> dict:
    """Compare extracted demographics against a database record.

    Args:
        extracted: Dict with keys like full_name, date_of_birth,
                   document_number, gender, address, father_or_spouse_name
        db_record: Dict with the same keys from citizens_registry

    Returns:
        {
            "comparisons": [
                {
                    "field": "Full Name",
                    "extracted": "Rajesh Kumar",
                    "database": "Rajesh Kumar",
                    "status": "match",
                    "confidence": 0.98
                },
                ...
            ],
            "overall_match": True/False,
            "match_count": int,
            "mismatch_count": int,
            "unverified_count": int,
            "mismatch_fields": ["Date of Birth"]  # list of mismatched field names
        }
    """
    comparisons = []

    # --- Full Name ---
    ext_name = extracted.get("full_name") or ""
    db_name = db_record.get("full_name") or ""
    name_sim = _token_sort_similarity(ext_name, db_name)
    NAME_THRESHOLD = 0.85
    comparisons.append({
        "field": "Full Name",
        "extracted": ext_name or None,
        "database": db_name or None,
        "status": "match" if name_sim >= NAME_THRESHOLD else (
            "mismatch" if ext_name and db_name else "unverified"
        ),
        "confidence": name_sim,
    })

    # --- Date of Birth ---
    ext_dob = extracted.get("date_of_birth") or ""
    db_dob = db_record.get("date_of_birth") or ""
    norm_ext_dob = _normalize_date(ext_dob)
    norm_db_dob = _normalize_date(db_dob)
    dob_match = norm_ext_dob == norm_db_dob if (norm_ext_dob and norm_db_dob) else None
    comparisons.append({
        "field": "Date of Birth",
        "extracted": ext_dob or None,
        "database": db_dob or None,
        "status": "match" if dob_match is True else (
            "mismatch" if dob_match is False else "unverified"
        ),
        "confidence": 1.0 if dob_match is True else (0.0 if dob_match is False else None),
    })

    # --- Document Number ---
    ext_doc = extracted.get("document_number") or ""
    db_doc = db_record.get("document_number") or ""
    norm_ext_doc = _normalize_doc_number(ext_doc)
    norm_db_doc = _normalize_doc_number(db_doc)
    doc_match = norm_ext_doc == norm_db_doc if (norm_ext_doc and norm_db_doc) else None
    comparisons.append({
        "field": "Document Number",
        "extracted": ext_doc or None,
        "database": db_doc or None,
        "status": "match" if doc_match is True else (
            "mismatch" if doc_match is False else "unverified"
        ),
        "confidence": 1.0 if doc_match is True else (0.0 if doc_match is False else None),
    })

    # --- Gender ---
    ext_gen = _normalize(extracted.get("gender"))
    db_gen = _normalize(db_record.get("gender"))
    gen_match = ext_gen == db_gen if (ext_gen and db_gen) else None
    comparisons.append({
        "field": "Gender",
        "extracted": extracted.get("gender"),
        "database": db_record.get("gender"),
        "status": "match" if gen_match is True else (
            "mismatch" if gen_match is False else "unverified"
        ),
        "confidence": 1.0 if gen_match is True else (0.0 if gen_match is False else None),
    })

    # --- Address (fuzzy + PIN code) ---
    ext_addr = extracted.get("address") or ""
    db_addr = db_record.get("address") or ""
    addr_sim = _token_sort_similarity(ext_addr, db_addr) if (ext_addr and db_addr) else None

    # Also check PIN code match separately (more reliable than full address)
    ext_pin = _extract_pin_code(ext_addr)
    db_pin = _extract_pin_code(db_addr)
    pin_match = ext_pin == db_pin if (ext_pin and db_pin) else None

    ADDR_THRESHOLD = 0.60  # addresses can vary significantly in formatting
    addr_status = "unverified"
    if addr_sim is not None:
        if addr_sim >= ADDR_THRESHOLD or pin_match is True:
            addr_status = "match"
        else:
            addr_status = "mismatch"

    comparisons.append({
        "field": "Address",
        "extracted": ext_addr or None,
        "database": db_addr or None,
        "status": addr_status,
        "confidence": addr_sim,
        "pin_code_match": pin_match,
    })

    # --- Father/Spouse Name ---
    ext_father = extracted.get("father_or_spouse_name") or ""
    db_father = db_record.get("father_or_spouse_name") or ""
    father_sim = _token_sort_similarity(ext_father, db_father) if (ext_father and db_father) else None
    father_status = "unverified"
    if father_sim is not None:
        father_status = "match" if father_sim >= NAME_THRESHOLD else "mismatch"
    comparisons.append({
        "field": "Father/Spouse Name",
        "extracted": ext_father or None,
        "database": db_father or None,
        "status": father_status,
        "confidence": father_sim,
    })

    # --- Aggregate ---
    match_count = sum(1 for c in comparisons if c["status"] == "match")
    mismatch_count = sum(1 for c in comparisons if c["status"] == "mismatch")
    unverified_count = sum(1 for c in comparisons if c["status"] == "unverified")
    mismatch_fields = [c["field"] for c in comparisons if c["status"] == "mismatch"]

    # Critical fields: Name, DOB, Document Number — any mismatch here fails overall
    critical = ["Full Name", "Date of Birth", "Document Number"]
    critical_mismatches = [f for f in mismatch_fields if f in critical]
    overall_match = len(critical_mismatches) == 0 and mismatch_count == 0

    return {
        "comparisons": comparisons,
        "overall_match": overall_match,
        "match_count": match_count,
        "mismatch_count": mismatch_count,
        "unverified_count": unverified_count,
        "mismatch_fields": mismatch_fields,
        "critical_mismatches": critical_mismatches,
    }
