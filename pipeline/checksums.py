"""Algorithmic checksum validators for Indian identity documents.

Post-processes AI-extracted document numbers to catch OCR digit hallucinations
on blurry cards. Each validator is pure-algorithmic (no ML) and deterministic.

Supported documents:
  * Aadhaar  — 12-digit Verhoeff checksum (last digit is check digit)
  * Passport — ICAO 9303 modulus-10 weights (7, 3, 1) for MRZ fields
  * PAN      — [A-Z]{5}[0-9]{4}[A-Z] regex syntax
  * Voter ID — EPIC alphanumeric format [A-Z]{3}[0-9]{7}
"""

from __future__ import annotations

import re
from typing import List, Optional







_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]


_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


_VERHOEFF_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def validate_verhoeff(number: str) -> bool:
    """Validate an Aadhaar number using the Verhoeff checksum algorithm.

    The 12th digit of a valid Aadhaar number is the Verhoeff check digit.
    Returns True if the number passes the checksum, False otherwise.

    Args:
        number: The Aadhaar number string (digits only, spaces/hyphens stripped).
    """

    digits = re.sub(r"[\s\-]", "", number)

    if not digits.isdigit():
        return False
    if len(digits) != 12:
        return False

    c = 0
    reversed_digits = list(map(int, reversed(digits)))
    for i, digit in enumerate(reversed_digits):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][digit]]

    return c == 0


def compute_verhoeff_digit(number: str) -> int:
    """Compute the Verhoeff check digit for the first 11 digits of an Aadhaar.

    Pure helper (not a ModuleResult module): raises ValueError on malformed
    input by design — callers must validate length first. Route-facing code
    catches this and degrades to inconclusive.

    Args:
        number: The first 11 digits of the Aadhaar number.

    Returns:
        The check digit (0-9).
    """
    digits = re.sub(r"[\s\-]", "", number)
    if not digits.isdigit() or len(digits) != 11:
        raise ValueError(f"Expected 11 digits, got: {digits!r}")

    c = 0
    reversed_digits = list(map(int, reversed(digits)))
    for i, digit in enumerate(reversed_digits):
        c = _VERHOEFF_D[c][_VERHOEFF_P[(i + 1) % 8][digit]]

    return _VERHOEFF_INV[c]






_ICAO_WEIGHTS = (7, 3, 1)


def _icao_char_value(c: str) -> int:
    """Map a single MRZ character to its numeric value per ICAO 9303."""
    if c.isdigit():
        return int(c)
    if c == "<" or c == "/":
        return 0
    if "A" <= c.upper() <= "Z":
        return ord(c.upper()) - ord("A") + 10
    return 0


def icao_check_digit(block: str) -> int:
    """Compute the ICAO 9303 check digit for a string block.

    Uses modulus-10 with weights (7, 3, 1) cycling.
    """
    total = 0
    for i, ch in enumerate(block):
        total += _icao_char_value(ch) * _ICAO_WEIGHTS[i % 3]
    return total % 10


def validate_icao_9303(mrz_lines: list[str]) -> dict:
    """Validate ICAO 9303 check digits across passport MRZ fields.

    Expects a list of 2 MRZ lines (TD3 format, 44 chars each).
    Returns a dict with validation results for each checkable field:
      - document_number: {ok: bool, given: int, computed: int}
      - date_of_birth:   {ok: bool, given: int, computed: int}
      - date_of_expiry:  {ok: bool, given: int, computed: int}
      - composite:       {ok: bool, given: int, computed: int}
    """
    result = {}

    if not mrz_lines or len(mrz_lines) < 2:
        result["status"] = "insufficient_mrz_lines"
        return result

    raw1 = (mrz_lines[0] or "").strip()
    raw2 = (mrz_lines[1] or "").strip()
    if len(raw1) < 40 or len(raw2) < 40:
        result["status"] = "insufficient_mrz_lines"
        result["detail"] = "MRZ lines too short to validate (need >= 40 chars)"
        return result

    line1 = raw1.ljust(44, "<")[:44]
    line2 = raw2.ljust(44, "<")[:44]


    doc_num_block = line2[0:9]
    doc_num_check = line2[9]
    computed_doc = icao_check_digit(doc_num_block)
    result["document_number"] = {
        "ok": _icao_char_value(doc_num_check) == computed_doc,
        "given": _icao_char_value(doc_num_check),
        "computed": computed_doc,
    }


    dob_block = line2[13:19]
    dob_check = line2[19]
    computed_dob = icao_check_digit(dob_block)
    result["date_of_birth"] = {
        "ok": _icao_char_value(dob_check) == computed_dob,
        "given": _icao_char_value(dob_check),
        "computed": computed_dob,
    }


    exp_block = line2[21:27]
    exp_check = line2[27]
    computed_exp = icao_check_digit(exp_block)
    result["date_of_expiry"] = {
        "ok": _icao_char_value(exp_check) == computed_exp,
        "given": _icao_char_value(exp_check),
        "computed": computed_exp,
    }


    composite_block = line2[0:10] + line2[13:20] + line2[21:43]
    composite_check = line2[43]
    computed_comp = icao_check_digit(composite_block)
    result["composite"] = {
        "ok": _icao_char_value(composite_check) == computed_comp,
        "given": _icao_char_value(composite_check),
        "computed": computed_comp,
    }

    return result






_PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def validate_pan_format(pan: str) -> bool:
    """Validate Indian PAN card format: [A-Z]{5}[0-9]{4}[A-Z].

    Args:
        pan: The PAN string (10 characters, uppercase).

    Returns:
        True if the format matches the PAN specification.
    """
    cleaned = pan.strip().upper()
    return bool(_PAN_REGEX.match(cleaned))






_EPIC_REGEX = re.compile(r"^[A-Z]{3}[0-9]{7}$")


def validate_epic_format(epic: str) -> bool:
    """Validate Indian Voter ID EPIC format: [A-Z]{3}[0-9]{7}.

    Args:
        epic: The EPIC number (10 characters, uppercase letters + digits).

    Returns:
        True if the format matches the EPIC specification.
    """
    cleaned = epic.strip().upper()
    return bool(_EPIC_REGEX.match(cleaned))






def validate_document_number(doc_type: str, doc_number: str) -> dict:
    """Validate a document number based on its type.

    Returns:
        {
            "document_type": str,
            "document_number": str,
            "valid": bool,
            "method": str,
            "detail": str
        }
    """
    dt = (doc_type or "").lower().strip()
    num = (doc_number or "").strip()

    if dt == "aadhaar":
        ok = validate_verhoeff(num)
        return {
            "document_type": "aadhaar",
            "document_number": num,
            "valid": ok,
            "method": "verhoeff_checksum",
            "detail": "12th digit Verhoeff check"
                      + (" passed" if ok else " failed"),
        }
    elif dt == "pan":
        ok = validate_pan_format(num)
        return {
            "document_type": "pan",
            "document_number": num,
            "valid": ok,
            "method": "regex_syntax",
            "detail": "[A-Z]{5}[0-9]{4}[A-Z]"
                      + (" matched" if ok else " not matched"),
        }
    elif dt == "voter_id":
        ok = validate_epic_format(num)
        return {
            "document_type": "voter_id",
            "document_number": num,
            "valid": ok,
            "method": "regex_syntax",
            "detail": "[A-Z]{3}[0-9]{7}"
                      + (" matched" if ok else " not matched"),
        }
    elif dt == "passport":
        return {
            "document_type": "passport",
            "document_number": num,
            "valid": None,
            "method": "icao_9303",
            "detail": "Use validate_icao_9303() with full MRZ lines for ICAO validation",
        }
    else:
        return {
            "document_type": dt,
            "document_number": num,
            "valid": None,
            "method": "unsupported",
            "detail": f"No validator for document type: {dt}",
        }
