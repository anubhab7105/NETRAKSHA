"""Gemini AI Multi-Task Scanner — single-call document analysis.

Sends a single multi-image request to Google Gemini 1.5/2.0 Flash containing:
  1. Uploaded Document Image
  2. Live Webcam Capture Still
  3. Database Reference Photo (optional)

In a single ~1.4-second roundtrip, Gemini returns a structured JSON payload
with document classification, OCR demographics, 3-way face verification,
and photo tamper anomaly detection.

Includes a resilient **offline simulation fallback engine** so the system
executes smoothly even if an API key is not configured or during network
timeouts. The fallback produces realistic demo output marked with
`is_simulated: true`.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

# Load project .env so GEMINI_API_KEY / GEMINI_MODEL are available even
# when the backend is started without exported environment variables.
load_dotenv()

# ---------------------------------------------------------------------------
# Gemini API integration
# ---------------------------------------------------------------------------

_GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

# The structured prompt for multi-task document analysis
_SYSTEM_PROMPT = """You are an expert border security document forensics AI.
Analyse the provided images and return ONLY a JSON object with this exact schema:

{
  "document_type": "aadhaar | pan | voter_id | passport | unknown",
  "classification_confidence": <float 0.0-1.0>,
  "demographics": {
    "document_number": "<extracted document number>",
    "full_name": "<full name as printed>",
    "date_of_birth": "<YYYY-MM-DD>",
    "gender": "<M | F | Other>",
    "address": "<full address if visible>",
    "father_or_spouse_name": "<if visible, else null>"
  },
  "three_way_face_match": {
    "live_vs_doc_match": <bool>,
    "doc_vs_db_match": <bool or null if no DB photo>,
    "live_vs_db_match": <bool or null if no DB photo>,
    "similarity_score": <float 0.0-1.0>,
    "visual_reasoning": "<2-3 sentence forensic explanation>"
  },
  "photo_tamper_anomaly": <bool>
}

Rules:
- Image 1 is always the document image.
- Image 2 is the live webcam capture.
- Image 3 (if provided) is the database reference photo.
- For face matching, compare facial structure, jawline, ear geometry, interpupillary distance.
- For photo_tamper_anomaly, look for pasted/spliced/cut photo borders, inconsistent lighting around the photo region.
- If any field is unreadable, set it to null.
- Return ONLY valid JSON, no markdown fences, no commentary.
"""


def _load_image_bytes(image_path: str | Path) -> Optional[bytes]:
    """Load image bytes from a file path."""
    p = Path(image_path)
    if not p.exists():
        return None
    return p.read_bytes()


def _get_mime_type(image_path: str | Path) -> str:
    """Infer MIME type from file extension."""
    ext = Path(image_path).suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".gif": "image/gif",
    }.get(ext, "image/png")


_NO_LIVE_FACE_REASON = (
    "No live webcam image was provided for comparison. Facial biometric "
    "matching cannot be evaluated against the document photograph."
)


def _normalize_no_live_face_match(result: dict, has_live: bool) -> dict:
    """Make the advertised 3-way face-match block consistent with the input.

    Without a live capture the live-vs-* comparisons are meaningless, yet the
    model may still guess at them (e.g. a mismatch at 0% similarity). Reset
    those fields to None with an explicit reason so no consumer — the response
    OR the persisted module raw_output — can manufacture a face verdict.
    Doc-vs-DB stays as reported when a DB reference photo was supplied.
    """
    if has_live:
        return result
    fm = result.get("three_way_face_match") or {}
    if not isinstance(fm, dict):
        fm = {}
    fm = {
        **fm,
        "live_vs_doc_match": None,
        "live_vs_db_match": None,
        "similarity_score": None,
        "visual_reasoning": _NO_LIVE_FACE_REASON,
    }
    result["three_way_face_match"] = fm
    return result


def scan_document(
    document_image_path: str | Path,
    live_capture_path: Optional[str | Path] = None,
    db_reference_path: Optional[str | Path] = None,
    timeout: float = 10.0,
) -> dict:
    """Execute the single-call multi-task AI scan.

    Tries Google Gemini first; falls back to offline simulation if
    the API key is missing, the SDK isn't installed, or the call fails.

    Returns:
        A dict matching the structured JSON schema above, plus metadata fields:
          - `is_simulated`: bool — True if the fallback engine was used
          - `latency_ms`: float — roundtrip time in milliseconds
          - `model_used`: str — the model identifier or "offline_simulation"
    """
    start = time.perf_counter()
    has_live = bool(live_capture_path and _load_image_bytes(live_capture_path))

    # Attempt real Gemini call
    if _GEMINI_API_KEY:
        try:
            result = _call_gemini(
                document_image_path,
                live_capture_path,
                db_reference_path,
                timeout,
            )
            elapsed = (time.perf_counter() - start) * 1000
            result["is_simulated"] = False
            result["latency_ms"] = round(elapsed, 1)
            result["model_used"] = _GEMINI_MODEL
            return _normalize_no_live_face_match(result, has_live)
        except Exception as exc:
            # Network/cloud failure → controlled fallback, not a halt
            err_name = type(exc).__name__
            is_network = any(s in err_name.lower() or s in str(exc).lower() for s in ["timeout", "connection", "network", "unavailable", "dns", "socket", "503", "502", "504"])
            print(f"[gemini_scanner] Gemini API call failed ({'network' if is_network else 'other'}): {err_name}: {exc} — falling back to local checks, final verdict will be Yellow/Manual Review")
            # Fall through to simulation with cloud_unavailable flag

    # Offline simulation fallback — controlled, not a halt
    result = _simulate_scan(document_image_path, live_capture_path, db_reference_path)
    elapsed = (time.perf_counter() - start) * 1000
    result["is_simulated"] = True
    result["cloud_unavailable"] = bool(_GEMINI_API_KEY)  # True if key existed but call failed (network), False if no key (demo)
    result["latency_ms"] = round(elapsed, 1)
    result["model_used"] = "offline_simulation"
    result["cloud_fallback_reason"] = "network_or_api_failure" if _GEMINI_API_KEY else "no_api_key"
    return _normalize_no_live_face_match(result, has_live)


def _call_gemini(
    document_image_path: str | Path,
    live_capture_path: str | Path,
    db_reference_path: Optional[str | Path],
    timeout: float,
) -> dict:
    """Make a real Gemini API call with multi-image input."""
    from google import genai
    from google.genai import types
    from google.genai.errors import ClientError

    client = genai.Client(api_key=_GEMINI_API_KEY)

    # Build content parts
    parts = [_SYSTEM_PROMPT]

    # Image 1: Document
    doc_bytes = _load_image_bytes(document_image_path)
    if doc_bytes:
        parts.append(
            types.Part.from_bytes(
                data=doc_bytes, mime_type=_get_mime_type(document_image_path)
            )
        )
    else:
        parts.append("Image 1 (document): Not available")

    # Image 2: Live capture (optional — no webcam → face match is inconclusive)
    live_bytes = _load_image_bytes(live_capture_path) if live_capture_path else b""
    if live_bytes:
        parts.append(
            types.Part.from_bytes(
                data=live_bytes, mime_type=_get_mime_type(live_capture_path)
            )
        )
    else:
        parts.append("Image 2 (live capture): Not available — do not compare faces")

    # Image 3: DB reference (optional)
    if db_reference_path:
        db_bytes = _load_image_bytes(db_reference_path)
        if db_bytes:
            parts.append(
                types.Part.from_bytes(
                    data=db_bytes, mime_type=_get_mime_type(db_reference_path)
                )
            )
        else:
            parts.append("Image 3 (database reference): Not available")

    response = client.models.generate_content(
        model=_GEMINI_MODEL,
        contents=parts,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )

    # Parse the JSON response
    text = response.text.strip()
    # Remove potential markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
    return json.loads(text)


# ---------------------------------------------------------------------------
# Offline Simulation Fallback Engine
# ---------------------------------------------------------------------------

# Pre-configured demo profiles for realistic output
_DEMO_PROFILES = {
    "aadhaar": {
        "document_type": "aadhaar",
        "classification_confidence": 0.97,
        "demographics": {
            "document_number": "2345 6789 0123",
            "full_name": "Rajesh Kumar",
            "date_of_birth": "1988-04-12",
            "gender": "M",
            "address": "Flat 402, Shanti Vihar, Sector 15, Noida, UP - 201301",
            "father_or_spouse_name": "Ramesh Kumar",
        },
    },
    "pan": {
        "document_type": "pan",
        "classification_confidence": 0.96,
        "demographics": {
            "document_number": "ABCPD1234E",
            "full_name": "Rajesh Kumar",
            "date_of_birth": "1988-04-12",
            "gender": "M",
            "address": None,
            "father_or_spouse_name": "Ramesh Kumar",
        },
    },
    "voter_id": {
        "document_type": "voter_id",
        "classification_confidence": 0.95,
        "demographics": {
            "document_number": "ABC1234567",
            "full_name": "Rajesh Kumar",
            "date_of_birth": "1988-04-12",
            "gender": "M",
            "address": "Ward 12, Block B, New Delhi - 110001",
            "father_or_spouse_name": "Ramesh Kumar",
        },
    },
    "passport": {
        "document_type": "passport",
        "classification_confidence": 0.98,
        "demographics": {
            "document_number": "J8369854",
            "full_name": "Rajesh Kumar",
            "date_of_birth": "1988-04-12",
            "gender": "M",
            "address": "Flat 402, Shanti Vihar, New Delhi - 110001",
            "father_or_spouse_name": None,
        },
    },
}


def _simulate_scan(
    document_image_path: str | Path,
    live_capture_path: str | Path,
    db_reference_path: Optional[str | Path],
) -> dict:
    """Produce realistic simulated output for demo / offline execution.

    Randomly selects a demo profile and generates face match results
    with slight randomization for natural variance.
    """
    # Pick a random profile
    profile_key = secrets.choice(list(_DEMO_PROFILES.keys()))
    profile = _DEMO_PROFILES[profile_key].copy()
    demographics = profile["demographics"].copy()

    # Generate face match results
    has_db = db_reference_path is not None
    has_live = live_capture_path is not None
    similarity = round(secrets.SystemRandom().uniform(0.88, 0.96), 2)

    face_match = {
        "live_vs_doc_match": True if has_live else None,
        "doc_vs_db_match": True if has_db else None,
        "live_vs_db_match": True if has_db else None,
        "similarity_score": similarity if has_live else None,
        "visual_reasoning": (
            "Consistent facial structure, identical jawline contour, "
            "matching ear geometry, and consistent interpupillary distance "
            "across live capture and document photo. No evidence of photo "
            "manipulation at photo borders."
            if has_live
            else "No live capture was provided — face verification against "
                 "a live webcam still is not possible."
        ),
    }

    result = {
        "document_type": profile["document_type"],
        "classification_confidence": profile["classification_confidence"],
        "demographics": demographics,
        "three_way_face_match": face_match,
        "photo_tamper_anomaly": False,
    }

    return result


def simulate_mismatch_scan(
    document_image_path: str | Path,
    live_capture_path: str | Path,
    db_reference_path: Optional[str | Path] = None,
) -> dict:
    """Simulate a FAILED scan for testing — face mismatch + anomalies.

    Returns output with low similarity and detected anomalies.
    """
    result = _simulate_scan(document_image_path, live_capture_path, db_reference_path)

    result["three_way_face_match"] = {
        "live_vs_doc_match": False,
        "doc_vs_db_match": False if db_reference_path else None,
        "live_vs_db_match": False if db_reference_path else None,
        "similarity_score": round(secrets.SystemRandom().uniform(0.15, 0.35), 2),
        "visual_reasoning": (
            "Significant facial discrepancies detected: jawline contour diverges "
            "markedly, interpupillary distance differs by >12%, and ear geometry "
            "is inconsistent. Photo borders show luminance discontinuity suggesting "
            "possible photo substitution."
        ),
    }
    result["photo_tamper_anomaly"] = True

    return result
