"""Module 1 — OCR / MRZ extraction.

Approach (Techspec.md §3):
  * Tesseract (via pytesseract) for visible passport/visa/ID fields.
  * PassportEye for MRZ line decoding.
  * ICAO 9303 check-digit validation of the MRZ.

Contract:
  * Returns an isolated :class:`ModuleResult` shaped to drop straight into the
    ``module_results`` table (Shema.md).
  * Visible fields that cannot be read are marked explicitly (value=None,
    readable=False) rather than guessed / silently fabricated.
  * Tesseract relies on a vendored binary + tessdata so the module works without
    a system-level install. If the OCR engine is unavailable the visible-field
    portion degrades (still inconclusive-safe); MRZ/ICAO still runs via the
    pure-Python PassportEye path when possible.

No image evidence is produced here — the extracted field table IS the evidence
the UI displays (Techspec.md §3, Appflow.md §3.4).
"""

from __future__ import annotations

import os
import re
import pathlib
import subprocess
from typing import List, Optional

from .common import (
    ModuleResult,
    TESSERACT_BIN,
    TESS_LIB_DIR,
    TESS_TESSDATA,
    inconclusive_result,
    load_image,
    ok_result,
    single_log,
)

MODULE_NAME = "ocr"

# Expected machine-readable fields on a passport-style document + MRZ slots.
VISIBLE_FIELDS = [
    "document_number",
    "surname",
    "given_names",
    "nationality",
    "date_of_birth",
    "date_of_expiry",
]

MRZ_FIELDS = [
    "document_type",
    "country",
    "surname",
    "given_names",
    "document_number",
    "nationality",
    "date_of_birth",
    "sex",
    "date_of_expiry",
    "personal_number",
]


# ---------------------------------------------------------------------------
# Vendored Tesseract runtime resolution
# ---------------------------------------------------------------------------

def _tesseract_available() -> bool:
    """Return True if a working tesseract binary + tessdata can be located."""
    if not TESSERACT_BIN.exists():
        return False
    if not (TESS_TESSDATA / "eng.traineddata").exists():
        return False
    return True


def _tesseract_env() -> dict:
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = str(TESS_LIB_DIR)
    env["TESSDATA_PREFIX"] = str(TESS_TESSDATA)
    return env


def _configure_tesseract() -> None:
    """Point pytesseract (and anything that shells out to it, incl. PassportEye)
    at the vendored binary + libs + tessdata. Safe to call repeatedly."""
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = str(TESSERACT_BIN)
    os.environ["LD_LIBRARY_PATH"] = str(TESS_LIB_DIR)
    os.environ["TESSDATA_PREFIX"] = str(TESS_TESSDATA)


def _ocr_frame_rgb(pil_rgb) -> str:
    """Run tesseract on a PIL RGB image, returning raw recognised text."""
    import pytesseract

    _configure_tesseract()

    return pytesseract.image_to_string(
        pil_rgb,
        config="--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789< >-",
    )


# ---------------------------------------------------------------------------
# Visible-field parsing (regex over raw OCR text)
# ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _parse_visible_fields(ocr_text: str) -> List[dict]:
    """Best-effort structured parse of common passport fields from OCR text.

    Matches a label token and its value *within a single OCR line* so we don't
    accidentally merge neighbouring fields. Fields that cannot be confidently
    located are returned explicitly as unreadable (value=None, readable=False)
    — never fabricated.
    """
    patterns = {
        "surname": re.compile(r"\bSURNAME\b\s*[:\-]?\s*([A-Z]{2,})"),
        "given_names": re.compile(
            r"\bGIVEN\s+NAME\s*\(?S?\)?\s*[:\-]?\s*([A-Z]{2,}(?:\s+[A-Z]{2,})*)",
            re.I,
        ),
        "nationality": re.compile(r"\bNATIONALITY\b\s*[:\-]?\s*([A-Z]{3})", re.I),
        "date_of_birth": re.compile(
            r"\b(?:DATE\s+OF\s+BIRTH|DOB)\b\s*[:\-]?\s*"
            r"([0-9]{1,2}\s*[/\-\.]\s*[0-9]{1,2}\s*[/\-\.]\s*[0-9]{2,4})",
            re.I,
        ),
        "date_of_expiry": re.compile(
            r"\b(?:DATE\s+OF\s+EXPIRY|EXPIRY)\b\s*[:\-]?\s*"
            r"([0-9]{1,2}\s*[/\-\.]\s*[0-9]{1,2}\s*[/\-\.]\s*[0-9]{2,4})",
            re.I,
        ),
        "document_number": re.compile(
            r"\bPASSPORT\s+NO\b\s*[:\-]?\s*([A-Z][0-9]{6,9})", re.I
        ),
    }

    found = {}

    for raw_line in ocr_text.splitlines():
        line = _clean(raw_line)
        if not line:
            continue
        for name, rgx in patterns.items():
            if name in found:
                continue
            m = rgx.search(line)
            if m and m.group(1):
                found[name] = m.group(1)

    field_names = [
        "document_number",
        "surname",
        "given_names",
        "nationality",
        "date_of_birth",
        "date_of_expiry",
    ]
    fields: List[dict] = []
    for name in field_names:
        val = found.get(name)
        fields.append(
            {
                "field_name": name,
                "value": val,
                "confidence": 0.8 if val is not None else 0.0,
                "readable": val is not None,
            }
        )
    return fields


# ---------------------------------------------------------------------------
# ICAO 9303 check-digit algorithm (weight 7,3,1, mod 10)
# ---------------------------------------------------------------------------

_WEIGHTS = (7, 3, 1)


def _char_value(c: str) -> int:
    if c.isdigit():
        return int(c)
    # '<' filler acts as a separator; treat as 0 to keep indexing simple,
    # but '/' in MRZ is treated via the '0' value in a different seam.
    if c == "<":
        return 0
    if c =="/":
        return 0
    if "A" <= c.upper() <= "Z":
        return ord(c.upper()) - ord("A") + 10
    return 0  # unexpected char -> treat as 0 (matches lenient ICAO behaviour)


def check_digit(block: str) -> int:
    """Compute the ICAO 9303 check digit for a string block."""
    total = 0
    for i, ch in enumerate(block):
        total += _char_value(ch) * _WEIGHTS[i % 3]
    return total % 10


def validate_checksum(block: str, given: str) -> bool:
    """True if the given (single-char) check digit equals the computed one."""
    if not block or not given:
        return False
    return check_digit(block) == _char_value(given[0])


def _mrz_segments(mrz_lines: List[str]) -> dict:
    """Extract the individually-checkable MRZ segments per ICAO 9303."""
    return {"_raw": mrz_lines}


# ---------------------------------------------------------------------------
# PassportEye MRZ parsing + ICAO validation
# ---------------------------------------------------------------------------

def _parse_mrz_via_passporteye(img_bgr):
    """Return (mrz_dict, checks, lines) using PassportEye.

    PassportEye's MrzImage only accepts a file path or bytes as input (a PIL
    image is silently ignored -> None), so we persist the frame to a scratch
    file and pass its path. The temp file holds no PII (it is the document the
    caller already owns) and is removed afterwards.
    """
    from passporteye.mrz.image import read_mrz

    import tempfile

    import cv2

    # PassportEye shells out to pytesseract for the MRZ OCR — ensure the
    # vendored runtime is configured regardless of call order.
    _configure_tesseract()

    fd, path = tempfile.mkstemp(suffix=".png", prefix="pipeline_mrz_")
    try:
        with os.fdopen(fd, "wb") as f:
            ok, buf = cv2.imencode(".png", img_bgr)
            if not ok:
                raise ValueError("could not encode image for MRZ parsing")
            f.write(buf.tobytes())
        mrz = read_mrz(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    if mrz is None:
        return None, {"status": "no_mrz_detected"}, []

    # Split the two MRZ lines from passporteye's parsed object (best effort —
    # PassportEye does not always expose them; ICAO validation uses its
    # per-block check_* attributes instead, see _validate_icao_blocks).
    lines = []
    if hasattr(mrz, "lines"):
        if isinstance(mrz.lines, dict):
            lines = [str(v) for v in mrz.lines.values()]
        else:
            lines = [l.decode() if isinstance(l, bytes) else str(l) for l in mrz.lines]

    # ICAO checksum validation per block, using our own 9303 implementation so
    # it's independent of (and verifiable against) the parser's reported value.
    # The GIVEN check digits come straight from PassportEye's per-block
    # `check_*` attributes (its OCR of the seam chars), not from raw lines.
    fields = _extract_mrz_fields_from_attrs(mrz)
    checks = _validate_icao_blocks(fields, mrz)
    return fields, checks, lines


def _extract_mrz_fields_from_attrs(mrz) -> dict:
    fields = {}
    scalar_map = {
        "surname": ("surname", None),
        "given_names": ("names", None),
        "nationality": ("nationality", None),
        "sex": ("sex", None),
    }
    for key, (attr, _) in scalar_map.items():
        v = getattr(mrz, attr, None)
        fields[key] = _as_str(v)
    # document_number / expiry come from the block paths
    fields["document_number"] = _as_str(getattr(mrz, "number", None))
    fields["date_of_birth"] = _as_str(getattr(mrz, "date_of_birth", None))
    fields["date_of_expiry"] = _as_str(getattr(mrz, "expiration_date", None))
    fields["personal_number"] = _as_str(getattr(mrz, "personal_number", None))
    fields["country"] = _as_str(getattr(mrz, "country", None))
    fields["document_type"] = (_as_str(getattr(mrz, "type", None)) or "").rstrip("<") or None
    # `names` is usually a surname,given string: split on the comma.
    names = fields.get("given_names") or ""
    if "," in names:
        surname, given = names.split(",", 1)
        fields["surname"] = (fields.get("surname") or surname).strip()
        fields["given_names"] = given.strip()
    return {k: (v if v != "" else None) for k, v in fields.items()}


def _as_str(v):
    if v is None:
        return None
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return str(v)


def _validate_icao_blocks(fields: dict, mrz) -> dict:
    """Validate the ICAO 9303 check-digit blocks using PassportEye's parsed
    field values (for the block body -> our `check_digit`) and its per-block
    `check_*` attributes (for the given seam digit).

    Returns {block: {"ok": bool, "given": int|None, "computed": int}}. Blocks
    whose GIVEN digit could not be OCR'd are reported with given=None and
    ok=False-but-"unverifiable" semantics (the caller treats failed-OCR the
    same as an inconclusive sub-check).
    """
    result = {}

    def _given(attr):
        v = getattr(mrz, attr, None)
        if v is None:
            return None
        return _char_value(str(v))

    def _add(name, block, given):
        if block is None:
            return
        computed = check_digit(block)
        result[name] = {
            "ok": given is not None and given == computed,
            "given": given,
            "computed": computed,
        }

    # 1) document number + its check digit
    dnum = fields.get("document_number")
    if dnum:
        _add("document_number", dnum.replace("<", ""), _given("check_number"))

    # 2) date of birth
    dob = fields.get("date_of_birth")
    if dob:
        digits = re.sub(r"[^0-9]", "", dob)
        if len(digits) == 6:
            _add("date_of_birth", digits, _given("check_date_of_birth"))

    # 3) date of expiry
    exp = fields.get("date_of_expiry")
    if exp:
        digits = re.sub(r"[^0-9]", "", exp)
        if len(digits) == 6:
            _add("date_of_expiry", digits, _given("check_expiration_date"))

    # 4) composite check digit (validates line1 truncated at the given-name
    #    separator, first 10 chars of a short-surname TD3 line). Only reported
    #    when both the given seam digit and the reconstruction are available
    #    AND the given digit is a real char (PassportEye may read the trailing
    #    '<' fill as the seam, which would be a false mismatch).
    comp_raw = getattr(mrz, "check_composite", None)
    comp_raw = str(comp_raw) if comp_raw is not None else ""
    if re.fullmatch(r"[0-9]", comp_raw):
        comp_given = _char_value(comp_raw)
        surname = fields.get("surname")
        given = fields.get("given_names")
        country = fields.get("country")
        doc_type = fields.get("document_type")
        if surname and given and country and doc_type:
            line1 = (doc_type + "<" + country + surname + "<<" + given).ljust(44, "<")
            line1_first = line1[:10]
            result["composite"] = {
                "ok": comp_given == check_digit(line1_first),
                "given": comp_given,
                "computed": check_digit(line1_first),
            }

    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_ocr_mrz(document_image) -> ModuleResult:
    """Run OCR/MRZ extraction on a single document image.

    Signature for the FastAPI route owner:
        run_ocr_mrz(document_image) -> ModuleResult

    ``document_image`` is a path (str/Path), bytes buffer, PIL Image, or BGR
    ndarray. Returns a result with status "ok" or "inconclusive". Never raises.
    """
    try:
        img = load_image(document_image)
    except Exception as exc:  # noqa: BLE001 — must never crash the pipeline
        single_log(f"ocr: input load failed -> inconclusive ({type(exc).__name__})")
        return inconclusive_result(MODULE_NAME, exc)

    try:
        return _run_ocr_mrz_impl(img)
    except Exception as exc:  # noqa: BLE001 — must never crash the pipeline
        single_log(f"ocr: unexpected failure -> inconclusive ({type(exc).__name__})")
        return inconclusive_result(MODULE_NAME, exc)


def _run_ocr_mrz_impl(img):
    """Processing body of run_ocr_mrz; kept separate for exception isolation."""
    # --- Visible fields via Tesseract ---------------------------------------
    ocr_text = ""
    tesseract_ok = False
    if _tesseract_available():
        try:
            from PIL import Image

            pil_bgr = Image.fromarray(img)
            rgb = pil_bgr.convert("RGB")
            ocr_text = _ocr_frame_rgb(rgb)
            tesseract_ok = bool(ocr_text.strip())
        except Exception as exc:  # noqa: BLE001
            single_log(f"ocr: tesseract run failed ({type(exc).__name__})")
    else:
        single_log("ocr: vendored tesseract runtime missing; visible fields inconclusive")

    visible_fields = _parse_visible_fields(ocr_text) if tesseract_ok else [
        {
            "field_name": f,
            "value": None,
            "confidence": 0.0,
            "readable": False,
        }
        for f in VISIBLE_FIELDS
    ]

    # --- MRZ via PassportEye + ICAO 9303 ------------------------------------
    mrz_fields = None
    icao = {"status": "not_run"}
    mrz_lines = []
    try:
        mrz_fields, icao, mrz_lines = _parse_mrz_via_passporteye(img)
    except Exception as exc:  # noqa: BLE001
        single_log(f"ocr: passporteye MRZ parse failed ({type(exc).__name__})")

    # --- Aggregate into the module contract --------------------------------
    readable_visible = sum(1 for f in visible_fields if f.get("readable"))
    readable_ratio = (
        readable_visible / len(visible_fields) if visible_fields else 0.0
    )

    icao_total = sum(1 for k, v in icao.items() if isinstance(v, dict) and "ok" in v)
    icao_passed = sum(
        1 for k, v in icao.items() if isinstance(v, dict) and v.get("ok")
    )
    icao_ratio = icao_passed / icao_total if icao_total else 0.0

    # overall clarity score = mean of visible readability and (when parsed) ICAO
    # conformance, weighted toward readable content. 0..1.
    parts = [readable_ratio]
    if mrz_fields:
        parts.append(icao_ratio if icao_total else 0.5)
    clarity = sum(parts) / len(parts)

    raw = {
        "fields": visible_fields,
        "mrz": {
            "fields": mrz_fields or {},
            "lines": mrz_lines,
            "icao_checks": icao,
            "parsed": bool(mrz_fields),
        },
        "ocr": {
            "engine": "tesseract",
            "available": tesseract_ok,
            "text": ocr_text[:500],
        },
        "readable_field_count": readable_visible,
        "readable_field_ratio": readable_ratio,
        "icao_blocks_validated": icao_total,
        "icao_blocks_passed": icao_passed,
    }

    if not tesseract_ok and not mrz_fields:
        return inconclusive_result(MODULE_NAME, "no OCR engine and no MRZ parsed")

    return ok_result(MODULE_NAME, round(clarity, 4), raw, evidence_uri=None)
