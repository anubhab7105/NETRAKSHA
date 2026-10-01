"""Gemini AI Multi-Task Scanner — single-call document analysis.

Sends a single multi-image request to a configured Google Gemini model
(see GEMINI_MODELS / GEMINI_MODEL, default cascade:
  gemini-flash-lite-latest → gemini-3.5-flash → gemini-3-flash-preview)
containing:
  1. Uploaded Document Image
  2. Live Webcam Capture Still
  3. Database Reference Photo (optional)

In a single ~1.4-second roundtrip, Gemini returns a structured JSON payload
with document classification, OCR demographics, 3-way face verification,
and photo tamper anomaly detection.

Includes a **cascading multi-model fallback**: if the primary model fails
(overloaded, unavailable, or misconfigured), the scanner automatically
retries with the next model in the list before falling back to the
**offline simulation engine** (marked `is_simulated: true`).

Misconfiguration note: a non-Google key (valid Google keys start with
`AIza`) or all models failing fails exactly like a network outage —
`is_simulated=True` + `cloud_unavailable=True` — and the case is floored
at Yellow. Check the `[gemini_scanner]` log line and `.env`
(`GEMINI_API_KEY`, `GEMINI_MODELS=gemini-flash-lite-latest,gemini-3.5-flash`)
first when the UI shows "CLOUD UNAVAILABLE — Local Checks Only".
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv



load_dotenv()










DEFAULT_GEMINI_MODELS = ["gemini-3.6-flash", "gemini-flash-lite-latest", "gemini-3.5-flash"]

DEFAULT_GEMINI_MODEL = DEFAULT_GEMINI_MODELS[0]


def _get_api_key() -> str:
    """Read the API key lazily so `.env` changes apply without reimport."""
    return os.environ.get("GEMINI_API_KEY", "")


def _get_models() -> list[str]:
    """Return the ordered list of models to try, from most to least preferred.

    Resolution order:
      1. GEMINI_MODELS (comma-separated list, e.g. "gemini-flash-lite-latest,gemini-3.5-flash")
      2. GEMINI_MODEL  (single model name — backwards compatibility)
      3. DEFAULT_GEMINI_MODELS hardcoded cascade
    """
    multi = os.environ.get("GEMINI_MODELS", "").strip()
    if multi:
        return [m.strip() for m in multi.split(",") if m.strip()]
    single = os.environ.get("GEMINI_MODEL", "").strip()
    if single:


        cascade = [single]
        for fallback in DEFAULT_GEMINI_MODELS:
            if fallback not in cascade:
                cascade.append(fallback)
        return cascade
    return list(DEFAULT_GEMINI_MODELS)


def _get_model() -> str:
    """Legacy single-model getter — returns the first model in the cascade.

    Kept for backwards compatibility; new call-sites should use _get_models().
    """
    return _get_models()[0]




_GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)


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
    "live_vs_doc_match": <bool — true if live face matches document photo, false if not>,
    "doc_vs_db_match": <bool — REQUIRED true/false when Image 3 present; null ONLY if Image 3 absent>,
    "live_vs_db_match": <bool — REQUIRED true/false when Image 2 AND Image 3 present; null otherwise>,
    "similarity_score": <float 0.0-1.0 — live-vs-doc facial similarity>,
    "doc_vs_db_similarity": <float 0.0-1.0 — document photo vs DB reference; null if no Image 3>,
    "live_vs_db_similarity": <float 0.0-1.0 — live capture vs DB reference; null if no Image 2 or 3>,
    "visual_reasoning": "<2-3 sentence forensic explanation covering all compared pairs>"
  },
  "photo_tamper_anomaly": <bool>
}

Rules:
- Image 1 is always the document image.
- Image 2 is the live webcam capture (may be absent — if absent set live_vs_doc_match=null, live_vs_db_match=null).
- Image 3 (if provided) is the database reference photo for identity verification.
- CRITICAL: When Image 3 IS provided, doc_vs_db_match MUST be true or false — NEVER null. Compare the face in Image 1 (document photo) to the face in Image 3 (DB reference) using facial geometry: jawline, interpupillary distance, nasal bridge, ear shape. Similarity >= 0.55 = match.
- CRITICAL: When both Image 2 AND Image 3 are provided, live_vs_db_match MUST be true or false — NEVER null. Compare the live face (Image 2) to the DB reference (Image 3).
- Each pair (live_vs_doc, doc_vs_db, live_vs_db) is independent — do NOT infer one from another.
- For face matching, compare facial structure, jawline, ear geometry, interpupillary distance.
- For photo_tamper_anomaly, look for pasted/spliced/cut photo borders, inconsistent lighting around the photo region.
- If any demographic field is unreadable, set it to null.
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
        "live_vs_db_similarity": None,
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
    """Execute the single-call multi-task AI scan with cascading model fallback.

    Iterates through the model list from GEMINI_MODELS (or GEMINI_MODEL for
    backwards compatibility, or the built-in default cascade) and tries each
    in order. The first model to succeed returns its result immediately.
    Only when every model in the list has been exhausted does the system fall
    back to the offline simulation engine.

    Returns:
        A dict matching the structured JSON schema above, plus metadata fields:
          - `is_simulated`: bool — True if the fallback engine was used
          - `latency_ms`: float — roundtrip time in milliseconds
          - `model_used`: str — the model identifier or "offline_simulation"
          - `models_attempted`: list[str] — models tried before success/failure
    """
    start = time.perf_counter()
    has_live = bool(live_capture_path and _load_image_bytes(live_capture_path))
    api_key = _get_api_key()
    models = _get_models()


    fallback_reason: Optional[str] = None
    models_attempted: list[str] = []

    if api_key:
        for model in models:
            models_attempted.append(model)
            try:
                result = _call_gemini(
                    document_image_path,
                    live_capture_path,
                    db_reference_path,
                    timeout,
                    api_key=api_key,
                    model=model,
                )
                elapsed = (time.perf_counter() - start) * 1000
                result["is_simulated"] = False
                result["latency_ms"] = round(elapsed, 1)
                result["model_used"] = model
                result["models_attempted"] = models_attempted
                return _normalize_no_live_face_match(result, has_live)
            except Exception as exc:



                err_text = f"{type(exc).__name__}: {exc}".lower()
                is_auth = any(s in err_text for s in [
                    "api_key", "api key", "invalid key", "unauthenticated",
                    "permission_denied", "permission denied", "401", "403",
                ])
                is_model_error = any(s in err_text for s in [
                    "not found", "404", "is not found", "unsupported",
                    "does not exist", "unknown model", "publisher model",
                ])
                is_network = any(s in err_text for s in [
                    "timeout", "connection", "network", "unavailable",
                    "dns", "socket", "503", "502", "504", "deadline",
                    "resource_exhausted", "quota", "rate",
                ])

                if is_auth:


                    fallback_reason = "auth_or_config_error"
                    print(
                        f"[gemini_scanner] Auth/config error on model '{model}': "
                        f"{type(exc).__name__}: {exc} — aborting cascade. "
                        "Check .env: GEMINI_API_KEY must be a valid Google key "
                        "(starts with 'AIza')."
                    )
                    break
                elif is_model_error:
                    kind = "model-not-found"
                    fallback_reason = "network_or_api_failure"
                    print(
                        f"[gemini_scanner] Model '{model}' not found/unsupported "
                        f"({type(exc).__name__}: {exc}) — trying next model in cascade."
                    )

                elif is_network:
                    fallback_reason = "network_or_api_failure"
                    print(
                        f"[gemini_scanner] Network/quota error on model '{model}' "
                        f"({type(exc).__name__}: {exc}) — trying next model in cascade."
                    )

                else:
                    fallback_reason = "network_or_api_failure"
                    print(
                        f"[gemini_scanner] Unexpected error on model '{model}' "
                        f"({type(exc).__name__}: {exc}) — trying next model in cascade."
                    )


        if models_attempted:
            print(
                f"[gemini_scanner] All {len(models_attempted)} model(s) failed "
                f"({', '.join(models_attempted)}) — falling back to offline simulation. "
                "Final verdict will be Yellow/Manual Review."
            )


    result = _simulate_scan(document_image_path, live_capture_path, db_reference_path)
    elapsed = (time.perf_counter() - start) * 1000
    result["is_simulated"] = True

    _has_real_key = bool(
        api_key
        and api_key.strip() not in ("", "your_gemini_api_key_here", "your_gemini_api_key_here\n")
        and len(api_key.strip()) > 20
    )
    result["cloud_unavailable"] = bool(_has_real_key and fallback_reason is not None)
    if not _has_real_key:
        result["cloud_unavailable"] = False
    result["latency_ms"] = round(elapsed, 1)
    result["model_used"] = "offline_simulation"
    result["models_attempted"] = models_attempted
    result["cloud_fallback_reason"] = (
        (fallback_reason or "network_or_api_failure") if _has_real_key else "no_api_key"
    )
    return _normalize_no_live_face_match(result, has_live)


_GEMINI_EXECUTOR = None
_GEMINI_EXECUTOR_LOCK = None


def _gemini_executor():
    """Process-wide single worker for Gemini timeouts (no per-call threads)."""
    global _GEMINI_EXECUTOR, _GEMINI_EXECUTOR_LOCK
    if _GEMINI_EXECUTOR is None:
        import concurrent.futures as _futures
        import threading as _threading

        if _GEMINI_EXECUTOR_LOCK is None:
            _GEMINI_EXECUTOR_LOCK = _threading.Lock()
        with _GEMINI_EXECUTOR_LOCK:
            if _GEMINI_EXECUTOR is None:
                _GEMINI_EXECUTOR = _futures.ThreadPoolExecutor(
                    max_workers=2, thread_name_prefix="gemini-timeout"
                )
    return _GEMINI_EXECUTOR


def _generate_with_timeout(client, model: str, parts, timeout: float):
    """Run the blocking Gemini call with a hard timeout.

    The google-genai SDK call has no timeout parameter, so without this a
    stalled network/model hangs screening forever (frontend 90s axios timeout
    then reports "could not reach the backend"). Each model in the cascade
    gets at most `timeout` seconds before we raise TimeoutError and try the
    next model / offline simulation. A shared executor is reused — a timed-out
    worker thread is abandoned (it ends with the SDK call) instead of
    leaking an executor per screening.
    """
    import concurrent.futures

    try:
        timeout = float(timeout or 10.0)
    except (TypeError, ValueError):
        timeout = 10.0
    timeout = max(2.0, min(timeout, 60.0))

    def _do_call():
        from google.genai import types as _types

        return client.models.generate_content(
            model=model,
            contents=parts,
            config=_types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

    fut = _gemini_executor().submit(_do_call)
    try:
        return fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        raise TimeoutError(
            f"Gemini call timed out after {timeout:.0f}s (model={model})"
        ) from exc


def _call_gemini(
    document_image_path: str | Path,
    live_capture_path: str | Path,
    db_reference_path: Optional[str | Path],
    timeout: float,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """Make a real Gemini API call with multi-image input."""
    from google import genai
    from google.genai import types
    from google.genai.errors import ClientError

    api_key = api_key if api_key is not None else _get_api_key()
    model = model if model is not None else _get_model()
    client = genai.Client(api_key=api_key)


    parts = [_SYSTEM_PROMPT]


    doc_bytes = _load_image_bytes(document_image_path)
    if doc_bytes:
        parts.append(
            types.Part.from_bytes(
                data=doc_bytes, mime_type=_get_mime_type(document_image_path)
            )
        )
    else:
        parts.append("Image 1 (document): Not available")


    live_bytes = _load_image_bytes(live_capture_path) if live_capture_path else b""
    if live_bytes:
        parts.append(
            types.Part.from_bytes(
                data=live_bytes, mime_type=_get_mime_type(live_capture_path)
            )
        )
    else:
        parts.append("Image 2 (live capture): Not available — do not compare faces")


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

    response = _generate_with_timeout(client, model, parts, timeout)


    text = response.text.strip()

    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
    return json.loads(text)







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

    profile_key = secrets.choice(list(_DEMO_PROFILES.keys()))
    profile = _DEMO_PROFILES[profile_key].copy()
    demographics = profile["demographics"].copy()


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
