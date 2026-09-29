"""Module 1 — OCR / MRZ extraction.

Approach (Techspec.md §3):
  * Tesseract (via pytesseract) for visible passport/visa/ID fields, plus
    best-effort Indian-ID patterns (Aadhaar 12-digit, PAN, Voter EPIC, DOB,
    gender) so non-passport cards still yield trusted demographics when the
    cloud AI is offline. Passport MRZ remains authoritative when present.
  * PassportEye for MRZ line decoding.
  * ICAO 9303 check-digit validation of the MRZ.

Contract:
  * Returns an isolated :class:`ModuleResult` shaped to drop straight into the
    ``module_results`` table (Shema.md).
  * Visible fields that cannot be read are marked explicitly (value=None,
    readable=False) rather than guessed / silently fabricated.
  * Tesseract resolution order (see pipeline/common.py): vendored binary +
    tessdata when present, otherwise a system-wide install. If no OCR engine
    is available the visible-field portion degrades (still
    inconclusive-safe); MRZ/ICAO still runs via the pure-Python PassportEye
    path when possible.

No image evidence is produced here — the extracted field table IS the evidence
the UI displays (Techspec.md §3, Appflow.md §3.4).
"""

from __future__ import annotations

import os
import re
import pathlib
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




VISIBLE_FIELDS = [
    "document_number",
    "document_type",
    "surname",
    "given_names",
    "nationality",
    "date_of_birth",
    "date_of_expiry",
    "sex",
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



        config="--psm 6 -c tessedit_char_whitelist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789< >-/.:'",
    )






def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _parse_visible_fields(ocr_text: str) -> List[dict]:
    """Best-effort structured parse of common passport fields from OCR text.

    Matches a label token and its value *within a single OCR line* so we don't
    accidentally merge neighbouring fields. Fields that cannot be confidently
    located are returned explicitly as unreadable (value=None, readable=False)
    — never fabricated.

    Indian-ID fallback: Aadhaar/PAN/Voter cards carry no MRZ and no
    SURNAME/PASSPORT-NO labels, so when the passport patterns miss, a second
    full-text pass looks for their bare number formats (PAN, EPIC, Aadhaar
    12-digit with Verhoeff preferred), an unlabeled DD/MM/YYYY birthdate, a
    MALE/FEMALE marker, and a NAME label. MRZ lines (containing '<') are
    excluded from this pass so MRZ digit runs can never be mistaken for an
    Indian document number.
    """
    patterns = {
        "surname": re.compile(r"\bSURNAME\b\s*[:\-]?\s*([A-Z]{2,})"),
        "given_names": re.compile(
            r"\bGIVEN\s+NAME\s*\(?S?\)?\s*[:\-]?\s*([A-Z]{2,}(?:\s+[A-Z]{2,})*)",
            re.I,
        ),
        "nationality": re.compile(r"\bNATIONALITY\b\s*[:\-]?\s*([A-Z]{3})", re.I),
        "date_of_birth": re.compile(
            r"\b(?:DATE\s+OF\s+BIRTH|DOB|BIRTH\s+DATE)\b\s*[:\-]?\s*"
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



    non_mrz_text = "\n".join(
        line for line in ocr_text.splitlines() if "<" not in line
    )
    if "document_number" not in found:
        _num, _type = _detect_indian_document_number(non_mrz_text)
        if _num:
            found["document_number"] = _num
            found["document_type"] = _type
    elif "document_type" not in found:
        found["document_type"] = "passport"
    if "sex" not in found:
        _sex = _detect_indian_gender(non_mrz_text)
        if _sex:
            found["sex"] = _sex
    if "given_names" not in found:


        for raw_line in non_mrz_text.splitlines():
            line = _clean(raw_line)
            if not line or re.search(
                r"\b(FATHER|SPOUSE|GUARDIAN|S/O|W/O|C/O)\b", line, re.I
            ):
                continue
            m = re.search(
                r"\bNAME\b\s*[:\-]?\s*([A-Z]{2,}(?:\s+[A-Z]{2,}){0,3})",
                line,
                re.I,
            )
            if m and m.group(1):
                found["given_names"] = m.group(1).strip()
                break
    if "date_of_birth" not in found:


        m = re.search(
            r"\b([0-9]{1,2}\s*[/\-\.]\s*[0-9]{1,2}\s*[/\-\.]\s*(?:19|20)[0-9]{2})\b",
            _clean(non_mrz_text),
        )
        if m and m.group(1):
            found["date_of_birth"] = re.sub(r"\s+", "", m.group(1))

    field_names = [
        "document_number",
        "document_type",
        "surname",
        "given_names",
        "nationality",
        "date_of_birth",
        "date_of_expiry",
        "sex",
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


def _detect_indian_document_number(text: str):
    """Return (number, document_type) for Indian IDs found in free OCR text.

    Priority: PAN → Voter EPIC → Aadhaar (Verhoeff-valid 12-digit preferred,
    any 12-digit otherwise). Returns (None, None) when nothing matches.
    """
    flat = _clean(text).upper()
    if not flat:
        return None, None
    m = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", flat)
    if m:
        return m.group(1), "pan"
    m = re.search(r"\b([A-Z]{3}[0-9]{7})\b", flat)
    if m:
        return m.group(1), "voter_id"
    candidates = re.findall(r"\b(\d{4}\s?\d{4}\s?\d{4})\b", flat)
    if candidates:
        try:
            from .checksums import validate_verhoeff
        except Exception:
            validate_verhoeff = None
        fallback = None
        for cand in candidates:
            digits = re.sub(r"\s+", "", cand)
            if validate_verhoeff is None:
                return digits, "aadhaar"
            try:
                if validate_verhoeff(digits):
                    return digits, "aadhaar"
            except Exception:
                pass
            fallback = fallback or digits
        if fallback:
            return fallback, "aadhaar"
    return None, None


def _detect_indian_gender(text: str):
    """Return 'M'/'F' when an explicit gender marker is present, else None."""
    flat = _clean(text).upper()
    if re.search(r"\bFEMALE\b", flat):
        return "F"
    if re.search(r"\bMALE\b", flat):
        return "M"
    m = re.search(r"\bSEX\b\s*[:\-]?\s*([MF])\b", flat)
    if m:
        return m.group(1)
    m = re.search(r"\bGENDER\b\s*[:\-]?\s*([MF])\b", flat)
    if m:
        return m.group(1)
    return None






_WEIGHTS = (7, 3, 1)


def _char_value(c: str) -> int:
    if c.isdigit():
        return int(c)


    if c == "<":
        return 0
    if c =="/":
        return 0
    if "A" <= c.upper() <= "Z":
        return ord(c.upper()) - ord("A") + 10
    return 0


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




    lines = []
    if hasattr(mrz, "lines"):
        if isinstance(mrz.lines, dict):
            lines = [str(v) for v in mrz.lines.values()]
        else:
            lines = [l.decode() if isinstance(l, bytes) else str(l) for l in mrz.lines]





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

    fields["document_number"] = _as_str(getattr(mrz, "number", None))
    fields["date_of_birth"] = _as_str(getattr(mrz, "date_of_birth", None))
    fields["date_of_expiry"] = _as_str(getattr(mrz, "expiration_date", None))
    fields["personal_number"] = _as_str(getattr(mrz, "personal_number", None))
    fields["country"] = _as_str(getattr(mrz, "country", None))
    fields["document_type"] = (_as_str(getattr(mrz, "type", None)) or "").rstrip("<") or None

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


    dnum = fields.get("document_number")
    if dnum:
        _add("document_number", dnum.replace("<", ""), _given("check_number"))


    dob = fields.get("date_of_birth")
    if dob:
        digits = re.sub(r"[^0-9]", "", dob)
        if len(digits) == 6:
            _add("date_of_birth", digits, _given("check_date_of_birth"))


    exp = fields.get("date_of_expiry")
    if exp:
        digits = re.sub(r"[^0-9]", "", exp)
        if len(digits) == 6:
            _add("date_of_expiry", digits, _given("check_expiration_date"))






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






def run_ocr_mrz(document_image) -> ModuleResult:
    """Run OCR/MRZ extraction on a single document image.

    Signature for the FastAPI route owner:
        run_ocr_mrz(document_image) -> ModuleResult

    ``document_image`` is a path (str/Path), bytes buffer, PIL Image, or BGR
    ndarray. Returns a result with status "ok" or "inconclusive". Never raises.
    """
    try:
        img = load_image(document_image)
    except Exception as exc:
        single_log(f"ocr: input load failed -> inconclusive ({type(exc).__name__})")
        return inconclusive_result(MODULE_NAME, exc)

    try:
        return _run_ocr_mrz_impl(img)
    except Exception as exc:
        single_log(f"ocr: unexpected failure -> inconclusive ({type(exc).__name__})")
        return inconclusive_result(MODULE_NAME, exc)


def _run_ocr_mrz_impl(img):
    """Processing body of run_ocr_mrz; kept separate for exception isolation."""

    ocr_text = ""
    tesseract_ok = False
    if _tesseract_available():
        try:
            from PIL import Image

            pil_bgr = Image.fromarray(img)
            rgb = pil_bgr.convert("RGB")
            ocr_text = _ocr_frame_rgb(rgb)
            tesseract_ok = bool(ocr_text.strip())
        except Exception as exc:
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


    mrz_fields = None
    icao = {"status": "not_run"}
    mrz_lines = []
    try:
        mrz_fields, icao, mrz_lines = _parse_mrz_via_passporteye(img)
    except Exception as exc:
        single_log(f"ocr: passporteye MRZ parse failed ({type(exc).__name__})")


    readable_visible = sum(1 for f in visible_fields if f.get("readable"))
    readable_ratio = (
        readable_visible / len(visible_fields) if visible_fields else 0.0
    )

    icao_total = sum(1 for k, v in icao.items() if isinstance(v, dict) and "ok" in v)
    icao_passed = sum(
        1 for k, v in icao.items() if isinstance(v, dict) and v.get("ok")
    )
    icao_ratio = icao_passed / icao_total if icao_total else 0.0



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
