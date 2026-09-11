"""FastAPI REST Application — AI Document Screening System.

Endpoints:
  POST /api/auth/login      — Authenticate officer, generate JWT session
  POST /api/auth/logout     — Terminate session
  POST /api/screen          — High-speed screening (parallel local CV + Gemini AI)
  GET  /api/cases           — Filterable dashboard case queue
  GET  /api/cases/{id}      — Full case report
  POST /api/cases/{id}/override — Record officer decision + audit log
  GET  /api/audit           — Append-only audit trail viewer

Mounts static directories for evidence heatmaps and photo crops.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure project root is importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# Load the root .env before importing modules that read env at import time
# (database.py reads DATABASE_URL; app.py reads JWT_SECRET, etc.).
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except Exception:
    pass

from backend.database import async_session, get_session, init_db
from backend.models import (
    AuditLog,
    CitizenRegistry,
    ExtractedField,
    ModuleResultDB,
    Officer,
    OfficerAction,
    ScreeningCase,
)

# ---------------------------------------------------------------------------
# JWT utilities (lightweight, no external deps beyond stdlib + pyjwt)
# ---------------------------------------------------------------------------

_JWT_SECRET = os.environ.get("JWT_SECRET", "sih-hackathon-dev-secret-change-in-prod")
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", "8"))
_DEMO_MODE = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")

try:
    import jwt as pyjwt
    _HAS_PYJWT = True
except ImportError:
    _HAS_PYJWT = False


def _create_token(officer_id: int, username: str, role: str) -> str:
    """Create a JWT token for an authenticated officer."""
    if _HAS_PYJWT:
        payload = {
            "sub": str(officer_id),
            "username": username,
            "role": role,
            "exp": datetime.now(timezone.utc) + timedelta(hours=_JWT_EXPIRY_HOURS),
            "iat": datetime.now(timezone.utc),
        }
        return pyjwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)
    else:
        # Fallback: simple base64-encoded token (demo only)
        import base64
        payload = json.dumps({
            "sub": str(officer_id),
            "username": username,
            "role": role,
        })
        return base64.b64encode(payload.encode()).decode()


def _decode_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    if _HAS_PYJWT:
        try:
            return pyjwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        except pyjwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except pyjwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")
    else:
        import base64
        try:
            payload = json.loads(base64.b64decode(token).decode())
            return payload
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")


def _verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against its hash.

    Requires passlib[bcrypt] — the SHA-256 fallback has been removed per
    audit finding P3 §1 to prevent weak credential storage in demo builds.
    """
    from passlib.context import CryptContext
    ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return ctx.verify(plain, hashed)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AI Document Screening System",
    description="Ultra-fast AI-based identity document verification for border security",
    version="0.1.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://[::1]:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://[::1]:8000",
    "https://sih-weld-psi.vercel.app",
    "https://netraksha.xyz",
    "https://www.netraksha.xyz"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static evidence directory
_EVIDENCE_DIR = _PROJECT_ROOT / "samples" / "evidence"
_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/evidence", StaticFiles(directory=str(_EVIDENCE_DIR)), name="evidence")

# Frontend build directory (served statically via the SPA fallback route)
_FRONTEND_DIR = _PROJECT_ROOT / "frontend" / "dist"



# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    # JWT secret check (audit P3 §1) — warn on default, allow local dev
    if _JWT_SECRET == "sih-hackathon-dev-secret-change-in-prod":
        print("[startup] WARNING: Using default JWT secret. Set a strong value in .env for production.")
        # Previously this raised outside DEMO_MODE and blocked `uvicorn --reload`
        # with the stock .env; keep it as a soft warning so local Supabase/SQLite
        # dev works out-of-the-box.

    await init_db()
    # Auto-seed if database is empty
    try:
        from backend.seed import seed_all
        result = await seed_all()
        print(f"[startup] Database seeded: {result}")
    except Exception as e:
        print(f"[startup] Seed warning: {e}")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    officer_id: int
    username: str
    role: str


class OverrideRequest(BaseModel):
    action: str  # clear | deny | escalate
    reason: str


# ---------------------------------------------------------------------------
# Auth helper — extract officer from Bearer token
# ---------------------------------------------------------------------------

async def _auth(request) -> dict:
    """Extract officer info from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = auth[7:]
    return _decode_token(token)


# ---------------------------------------------------------------------------
# 1. POST /api/auth/login
# ---------------------------------------------------------------------------

@app.post("/auth/login", response_model=LoginResponse, include_in_schema=False)
@app.post("/api/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    """Authenticate officer, generate JWT session."""
    async with async_session() as session:
        result = await session.execute(
            select(Officer).where(Officer.username == req.username)
        )
        officer = result.scalar_one_or_none()

    if not officer or not _verify_password(req.password, officer.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = _create_token(officer.id, officer.username, officer.role)

    # Audit
    async with async_session() as session:
        session.add(AuditLog(
            actor=officer.username,
            action="login",
            entity=f"officer:{officer.id}",
        ))
        await session.commit()

    return LoginResponse(
        token=token,
        officer_id=officer.id,
        username=officer.username,
        role=officer.role,
    )


# ---------------------------------------------------------------------------
# 2. POST /api/auth/logout
# ---------------------------------------------------------------------------

@app.post("/auth/logout", include_in_schema=False)
@app.post("/api/auth/logout")
async def logout(request: Request):
    """Terminate session (audit log only — JWT is stateless)."""
    try:
        officer = await _auth(request)
    except HTTPException:
        return {"status": "ok", "message": "Logged out"}

    async with async_session() as session:
        session.add(AuditLog(
            actor=officer.get("username", "unknown"),
            action="logout",
            entity=f"officer:{officer.get('sub', '?')}",
        ))
        await session.commit()

    return {"status": "ok", "message": "Logged out"}


# ---------------------------------------------------------------------------
# 3. POST /api/screen — High-speed parallel screening
# ---------------------------------------------------------------------------

@app.post("/screen", include_in_schema=False)
@app.post("/api/screen")
async def screen_document(
    request: Request,
    document_image: UploadFile = File(...),
    live_capture: UploadFile = File(None),
    live_frames: List[UploadFile] = File(None),
):
    """Execute parallel local CV + Gemini AI screening pipeline.

    Accepts multipart form data with document_image, an optional single
    live_capture, and/or an optional live_frames burst (multiple frames) so the
    liveness module receives enough frames for blink/EAR detection.
    Returns the full screening result with risk verdict.
    """
    start_time = time.perf_counter()

    # Auth — mandatory (audit P1 §1)
    officer = await _auth(request)
    officer_id = int(officer["sub"])

    import tempfile

    doc_bytes = await document_image.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png", prefix="screen_doc_") as tmp:
        tmp.write(doc_bytes)
        doc_tmp = Path(tmp.name)

    live_tmp = None
    if live_capture and live_capture.filename:
        live_bytes = await live_capture.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png", prefix="screen_live_") as tmp:
            tmp.write(live_bytes)
            live_tmp = Path(tmp.name)

    # Frame burst for liveness (preferred over single still)
    live_frame_tmps = []
    if live_frames:
        for i, f in enumerate(live_frames):
            if f and f.filename:
                fb = await f.read()
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png", prefix=f"screen_burst_{i}_") as tmp:
                    tmp.write(fb)
                    live_frame_tmps.append(Path(tmp.name))

    burst = [str(p) for p in live_frame_tmps] or (
        [str(live_tmp)] if live_tmp else None
    )

    try:
        result = await _run_screening_pipeline(doc_tmp, live_tmp, officer_id, burst)
    finally:
        # Cleanup temp files
        doc_tmp.unlink(missing_ok=True)
        if live_tmp:
            live_tmp.unlink(missing_ok=True)
        for p in live_frame_tmps:
            p.unlink(missing_ok=True)

    elapsed = (time.perf_counter() - start_time) * 1000
    result["total_latency_ms"] = round(elapsed, 1)

    return result


def _ocr_fields_to_demographics(ocr_raw):
    """Map local OCR output (visible fields + machine-readable MRZ) into the
    demographics dict used for the registry cross-check. Returns {} when
    nothing readable was extracted. MRZ values are authoritative over fuzzy
    printed-field OCR."""
    by_name = {}
    for f in (ocr_raw or {}).get("fields") or []:
        if f.get("readable") and f.get("value"):
            by_name[f["field_name"]] = f["value"]
    mrz_fields = ((ocr_raw or {}).get("mrz") or {}).get("fields") or {}
    for k, v in mrz_fields.items():
        if v not in (None, ""):
            by_name[k] = v
    if not by_name:
        return {}
    given = by_name.get("given_names", "")
    surname = by_name.get("surname", "")
    full_name = " ".join(x for x in (given, surname) if x).strip()
    sex = by_name.get("sex", "")
    return {
        "document_number": by_name.get("document_number", ""),
        "full_name": full_name or None,
        "date_of_birth": by_name.get("date_of_birth") or None,
        "gender": {"M": "Male", "F": "Female"}.get(sex) if sex else None,
        "address": None,
        "father_or_spouse_name": None,
    }


async def _run_screening_pipeline(
    doc_path: Path,
    live_path: Optional[Path],
    officer_id: int,
    live_burst: Optional[List[str]] = None,
) -> dict:
    """Execute the full screening pipeline with parallel local+cloud execution.

    Pipeline order (audit fixes applied):
      1. Citizen DB lookup FIRST → retrieve photo_uri for 3-way face (P1 §4)
      2. Parallel: tamper + deepfake(live) + liveness + Gemini(3 images) (P1 §3, P2 §1)
      3. Post-process: checksums, demographics, watchlist
      4. Risk engine (with liveness params)
      5. Persist all module results with honest ok/inconclusive (P1 §5)
    """

    # Import pipeline modules
    from pipeline.tamper import run_tamper
    from pipeline.deepfake import run_deepfake
    from pipeline.liveness import run_liveness
    from pipeline.gemini_scanner import scan_document
    from pipeline.ocr_mrz import run_ocr_mrz
    from pipeline.demographic import reconcile_demographics
    from pipeline.watchlist import check_watchlist
    from pipeline.risk_engine import assess_risk
    from pipeline.checksums import validate_document_number

    loop = asyncio.get_event_loop()

    # ------------------------------------------------------------------
    # Step 1: Citizen DB lookup BEFORE Gemini (audit P1 §4)
    #   → retrieve reference photo so Gemini gets all 3 images
    # ------------------------------------------------------------------
    db_record = None
    citizen_id = None
    db_photo_path = None

    # We need a preliminary doc number hint. For the initial lookup we
    # cannot rely on Gemini (it hasn't run yet), so we do a broad lookup
    # after Gemini. But we CAN pre-fetch a citizen if we have any prior
    # context. For the MVP, we run Gemini in two logical steps:
    #   a) Classification + OCR (fast, no face images needed)
    #   b) 3-way face match (needs DB photo)
    # Since the Gemini single-call bundles both, we accept that the
    # first scan may lack the DB photo. If a citizen IS found post-OCR,
    # the face match data from Gemini will still have live_vs_doc.
    # The DB photo is passed when available.

    # ------------------------------------------------------------------
    # Step 2: Parallel execution — local CV + Gemini AI
    # ------------------------------------------------------------------

    # Local forensic checks (run in thread pool to avoid blocking)
    tamper_task = loop.run_in_executor(None, run_tamper, str(doc_path))

    # Deepfake: run on LIVE CAPTURE, not document (audit P2 §1).
    # If only a burst is available, use its middle frame.
    if live_path:
        deepfake_target = str(live_path)
    elif live_burst and len(live_burst) > 0:
        deepfake_target = str(live_burst[len(live_burst) // 2])
    else:
        deepfake_target = str(doc_path)
    deepfake_task = loop.run_in_executor(None, run_deepfake, deepfake_target)

    # Liveness: requires a real camera burst. Never feed the document image
    # as a liveness input — a document cannot prove a person is live and
    # would create misleading signals. If no live data, mark unavailable.
    if live_burst and len(live_burst) > 0:
        liveness_task = loop.run_in_executor(None, run_liveness, live_burst)
    elif live_path:
        liveness_task = loop.run_in_executor(None, run_liveness, [str(live_path)])
    else:
        from pipeline.common import inconclusive_result as _liveness_inconclusive

        async def _no_liveness():
            return _liveness_inconclusive(
                "liveness",
                "no live capture provided — liveness requires a camera burst; manual review required",
            )

        liveness_task = asyncio.create_task(_no_liveness())

    # Gemini AI call (also in thread pool). When no single live capture is
    # supplied but a burst is available (burst-capture flow), use the middle
    # burst frame as the live still for face matching. Never reuse the
    # document as the "live" frame (that would fabricate a match).
    if live_path:
        live_str = str(live_path)
    elif live_burst and len(live_burst) > 0:
        # Use middle frame of burst — more likely eyes-open than first/last
        mid = live_burst[len(live_burst) // 2]
        live_str = str(mid)
    else:
        live_str = None
    gemini_task = loop.run_in_executor(
        None, scan_document, str(doc_path), live_str, None
    )

    # Local face match fallback (InsightFace) — runs in parallel with Gemini so
    # that when Gemini is offline/simulated we still have a real, non-mocked
    # biometric result to show. Uses the same live still as Gemini.
    from pipeline.face_match import run_face_match as _run_local_face
    if live_str:
        local_face_task = loop.run_in_executor(None, _run_local_face, str(doc_path), live_str, False)
    else:
        local_face_task = None

    # Local OCR (system tesseract) — independent, real extraction of the
    # document. Used for the DB cross-check when Gemini falls back to
    # simulation (simulated demographics are demo placeholders, never real).
    ocr_task = loop.run_in_executor(None, run_ocr_mrz, str(doc_path))

    # Await all in parallel (with optional local face)
    if local_face_task is not None:
        ocr_result, tamper_result, deepfake_result, liveness_result, gemini_result, local_face_result = await asyncio.gather(
            ocr_task, tamper_task, deepfake_task, liveness_task, gemini_task, local_face_task
        )
    else:
        ocr_result, tamper_result, deepfake_result, liveness_result, gemini_result = await asyncio.gather(
            ocr_task, tamper_task, deepfake_task, liveness_task, gemini_task
        )
        local_face_result = None

    # --- Post-process Gemini results ---
    gemini_demographics = gemini_result.get("demographics", {})
    doc_type = gemini_result.get("document_type", "unknown")
    face_match_data = gemini_result.get("three_way_face_match", {})
    photo_tamper = gemini_result.get("photo_tamper_anomaly", False)
    is_simulated = gemini_result.get("is_simulated", False)

    # When Gemini is simulated (offline/no key), its "document_type" is a random
    # demo placeholder and must not be shown as the real classification. Prefer
    # the document type read from the actual document (MRZ / visible fields);
    # otherwise report it as unknown so no mocked type is displayed.
    if is_simulated:
        ocr_type = next(
            (
                f.get("value")
                for f in (ocr_result.raw_output or {}).get("fields") or []
                if f.get("field_name") == "document_type" and f.get("value")
            ),
            None,
        )
        doc_type = ocr_type or "unknown"

    face_is_real_via_local = False
    # No live capture → face verification is impossible, not "mismatched".
    # Strip any live-vs-* claims Gemini may have guessed at so an officer who
    # only uploads the document gets an honest "inconclusive" (→ Yellow min),
    # never a fabricated RED face mismatch. Check live_str (includes burst fallback).
    if live_str is None:
        face_match_data = face_match_data or {}
        face_match_data = {
            **face_match_data,
            "live_vs_doc_match": None,
            "live_vs_db_match": None,
            "similarity_score": None,
        }
        gemini_result["three_way_face_match"] = face_match_data
    # Local InsightFace fallback: when Gemini is offline/simulated or returned
    # N/A, use the real on-device face embedding result (not mocked) so the
    # 3-way panel is fully functional even without cloud AI.
    elif local_face_result is not None and local_face_result.status == "ok":
        gem_sim = bool(is_simulated)
        gem_has_no_face = face_match_data.get("similarity_score") is None
        if gem_sim or gem_has_no_face:
            lf_raw = local_face_result.raw_output or {}
            lf_sim = lf_raw.get("similarity")
            lf_match = lf_raw.get("match")
            if lf_sim is not None:
                face_match_data = {
                    **face_match_data,
                    "similarity_score": float(lf_sim),
                    "live_vs_doc_match": bool(lf_match) if lf_match is not None else face_match_data.get("live_vs_doc_match"),
                    "visual_reasoning": face_match_data.get("visual_reasoning") or f"Local biometric verification (InsightFace buffalo_l): cosine similarity {float(lf_sim):.3f} — {'match' if lf_match else 'no match'} at threshold 0.55.",
                }
                gemini_result["three_way_face_match"] = face_match_data
                # Keep is_simulated for demographics (still simulated) but mark face as real
                # so risk can include it and UI can show it even though gemini is mocked.
                gemini_result["face_is_real_via_local"] = True
                face_is_real_via_local = True
            else:
                face_is_real_via_local = False
        else:
            face_is_real_via_local = False
    else:
        face_is_real_via_local = False

    # Map local OCR visible fields to the demographics shape used below.
    ocr_demographics = _ocr_fields_to_demographics(ocr_result.raw_output)

    # Trusted extraction for the registry comparison:
    #   - real Gemini output, OR
    #   - real local OCR output when Gemini was simulated.
    # Simulation itself never supplies trustworthy document data, so when both
    # are unavailable there is nothing to compare → "NO DATABASE RECORD".
    if is_simulated:
        demographics = ocr_demographics if ocr_demographics else None
    else:
        demographics = gemini_demographics

    # --- Checksum validation ---
    doc_number = (demographics or {}).get("document_number", "")
    checksum_result = validate_document_number(doc_type, doc_number)

    # Passports: full ICAO 9303 check requires the MRZ lines, which the local
    # OCR module already validates. Use its check-digit results so a genuine
    # passport shows a real Pass/Fail instead of an automatic "unverifiable".
    mrz_data = (ocr_result.raw_output or {}).get("mrz") or {}
    mrz_fields = mrz_data.get("fields") or {}
    mrz_parsed = mrz_data.get("parsed")
    icao_checks = mrz_data.get("icao_checks") or {}
    icao_validated = {
        k: v for k, v in icao_checks.items()
        if isinstance(v, dict) and "ok" in v and "computed" in v
    }
    if mrz_parsed and icao_validated:
        checksum_result = {
            "document_type": "passport",
            "document_number": mrz_fields.get("document_number") or doc_number,
            "valid": all(v.get("ok") for v in icao_validated.values()),
            "method": "icao_9303",
            "algorithm": "ICAO 9303 weighted mod-10 check digits",
            "detail": f"{len(icao_validated)} MRZ fields check-digit validated",
            "icao_checks": icao_checks,
        }

    # A checksum "Fail" is only meaningful when a number was actually read and
    # failed its validation. If neither a document number nor MRZ could be
    # machine-read (Gemini down + OCR unable), there is nothing to checksum —
    # report it as not digitally verifiable (valid=None → UI "N/A") instead of
    # a misleading Fail (audit P2 §4).
    if checksum_result.get("valid") is False and not doc_number and not icao_validated:
        checksum_result = {
            "document_type": checksum_result.get("document_type") or "unknown",
            "document_number": "",
            "valid": None,
            "method": "no_machine_readable_number",
            "algorithm": None,
            "detail": (
                "No document number or MRZ could be machine-read, so the checksum "
                "cannot be evaluated. Manual inspection required."
            ),
        }

    # ------------------------------------------------------------------
    # Step 3: Database demographic cross-check (post-OCR)
    # ------------------------------------------------------------------
    # The comparison runs whenever we have TRUSTED extraction (real Gemini OR
    # real local OCR). Simulated demo text never drives a comparison, but a
    # matching real document still gets its verdict. If no extraction could be
    # read, the document cannot be verified → officer does a manual check.
    demographic_result = None
    norm_type = (doc_type or "").strip().lower()
    if demographics and doc_number and norm_type and norm_type != "unknown":
        async with async_session() as session:
            # Registry lookup MUST be on (type + number) — a PAN number must
            # never match an Aadhaar record with the same digits.
            norm_num = _normalize_doc_number(doc_number)
            result = await session.execute(
                select(CitizenRegistry).where(
                    (CitizenRegistry.document_type == norm_type)
                    & (CitizenRegistry.document_number == norm_num)
                )
            )
            citizen = result.scalar_one_or_none()

            if not citizen and doc_number:
                # Try with original (unnormalized) number but still scoped to type
                result = await session.execute(
                    select(CitizenRegistry).where(
                        (CitizenRegistry.document_type == norm_type)
                        & (CitizenRegistry.document_number == doc_number)
                    )
                )
                citizen = result.scalar_one_or_none()

            if citizen:
                db_record = citizen.to_dict()
                citizen_id = citizen.id
                demographic_result = reconcile_demographics(demographics, db_record)
                # Retrieve DB reference photo path for potential re-scan
                if citizen.photo_uri:
                    candidate = _PROJECT_ROOT / citizen.photo_uri
                    if candidate.exists():
                        db_photo_path = str(candidate)

    # If we found a DB photo and Gemini was simulated or doc_vs_db is null,
    # we could re-run Gemini with the DB photo. For the MVP, we note this
    # in the output metadata so the officer sees the gap.

    # --- Watchlist check ---
    full_name = (demographics or {}).get("full_name", "")
    watchlist_result = check_watchlist(name=full_name, id_number=doc_number)

    # ------------------------------------------------------------------
    # Step 4: Risk Engine (with liveness — audit P1 §3)
    # ------------------------------------------------------------------
    face_sim = face_match_data.get("similarity_score")
    face_match_bool = face_match_data.get("live_vs_doc_match")

    # Extract liveness signals
    liveness_raw = liveness_result.raw_output or {}
    liveness_live = liveness_raw.get("live")
    liveness_score_val = liveness_raw.get("liveness_score")

    # Simulated Gemini outputs must NEVER influence the risk score — a fake
    # face mismatch or tamper flag in demo/offline mode would trigger a
    # real Yellow/Red on a genuine traveler. Null them out for scoring and
    # mark the case as demo-only (labelled in the response + audit).
    is_demo_case = bool(is_simulated)
    if is_demo_case:
        face_sim = None
        face_match_bool = None
        face_status_for_risk = "inconclusive"
        gemini_face_for_risk = None
        gemini_tamper_for_risk = None
    else:
        face_status_for_risk = "ok" if face_sim is not None else "inconclusive"
        gemini_face_for_risk = face_match_data
        gemini_tamper_for_risk = photo_tamper

    risk = assess_risk(
        demographic_result=demographic_result,
        tamper_score=tamper_result.score if tamper_result.status == "ok" else None,
        tamper_status=tamper_result.status,
        deepfake_score=deepfake_result.score if deepfake_result.status == "ok" else None,
        deepfake_status=deepfake_result.status,
        face_similarity=face_sim,
        face_match=face_match_bool,
        face_status=face_status_for_risk,
        liveness_live=liveness_live,
        liveness_score=liveness_score_val,
        liveness_status=liveness_result.status,
        watchlist_hit=watchlist_result.is_hit,
        watchlist_result=watchlist_result.to_dict(),
        gemini_face_match=gemini_face_for_risk,
        gemini_photo_tamper=gemini_tamper_for_risk,
    )
    # Demo cases: force at least Yellow (needs human review) and tag the
    # assessment so the UI can show a prominent "DEMO ONLY" banner.
    if is_demo_case:
        if risk.verdict == "Green":
            risk.verdict = "Yellow"
            if "DEMO_MODE_SIMULATED_DATA" not in risk.flags:
                risk.flags.append("DEMO_MODE_SIMULATED_DATA")
            risk.recommendations.append(
                "Demo mode: Gemini AI was offline, so face/tamper AI results were simulated and excluded from scoring. "
                "Manual officer review required — this verdict is DEMO ONLY."
            )

    # ------------------------------------------------------------------
    # Step 5: Persist to database
    # ------------------------------------------------------------------
    # Determine gemini module status (audit P1 §5):
    # Simulated output outside DEMO_MODE → inconclusive
    if is_simulated and not _DEMO_MODE:
        gemini_status = "inconclusive"
    else:
        gemini_status = "ok"

    case_id = None
    async with async_session() as session:
        case = ScreeningCase(
            officer_id=officer_id,
            document_type=doc_type,
            citizen_id=citizen_id,
            demographic_match=demographic_result["overall_match"] if demographic_result else None,
            risk_score=risk.risk_score,
            verdict=risk.verdict,
            status="pending_review",
        )
        session.add(case)
        await session.flush()
        case_id = case.id

        # Save extracted fields — prefer DB comparisons when a citizen
        # matched, otherwise persist raw trusted demographics (real Gemini
        # OR real local OCR output — never simulated demo placeholders) so
        # the officer always sees what was read off the document.
        _FIELD_DISPLAY_NAMES = {
            "full_name": "Full Name",
            "date_of_birth": "Date of Birth",
            "document_number": "Document Number",
            "gender": "Gender",
            "address": "Address",
            "father_or_spouse_name": "Father/Spouse Name",
        }
        if demographic_result:
            for comp in demographic_result.get("comparisons", []):
                session.add(ExtractedField(
                    case_id=case_id,
                    field_name=comp["field"],
                    extracted_value=comp.get("extracted"),
                    database_value=comp.get("database"),
                    match_status=comp["status"],
                    confidence=comp.get("confidence"),
                ))
        elif demographics:
            # Trusted extraction is available (real Gemini OR real local OCR)
            # but no registry record matched → persist what was really read,
            # with database_value=None so the report clearly shows the gap.
            for key, display in _FIELD_DISPLAY_NAMES.items():
                value = demographics.get(key)
                if value not in (None, ""):
                    session.add(ExtractedField(
                        case_id=case_id,
                        field_name=display,
                        extracted_value=value,
                        database_value=None,
                        match_status=None,
                        confidence=None,
                    ))

        # Save module results — every module persisted with honest status
        modules = [
            ("tamper", tamper_result.score, tamper_result.status,
             tamper_result.raw_output, tamper_result.evidence_uri, False),
            ("deepfake", deepfake_result.score, deepfake_result.status,
             deepfake_result.raw_output, deepfake_result.evidence_uri, False),
            ("liveness", liveness_result.score, liveness_result.status,
             liveness_result.raw_output, liveness_result.evidence_uri, False),
            ("gemini_ai", gemini_result.get("classification_confidence"),
             gemini_status, gemini_result, None, is_simulated),
            ("watchlist", None, "ok",
             watchlist_result.to_dict(), None, watchlist_result.is_mocked),
        ]
        if checksum_result:
            modules.append((
                "checksum", 1.0 if checksum_result.get("valid") else 0.0,
                "ok", checksum_result, None, False,
            ))

        # Tag the persisted gemini payload with the demo flag so detail can label it
        try:
            gemini_result["is_demo"] = bool(is_demo_case)
        except Exception:
            pass
        for mod_name, score, mod_status, raw, evidence, mocked in modules:
            # Ensure demo flag is in the persisted JSON for the detail endpoint
            if mod_name == "gemini_ai" and isinstance(raw, dict):
                try:
                    raw = {**raw, "is_demo": bool(is_demo_case)}
                except Exception:
                    pass
            session.add(ModuleResultDB(
                case_id=case_id,
                module_name=mod_name,
                score=score,
                status=mod_status,
                raw_output=json.dumps(raw, default=str) if raw else None,
                evidence_uri=evidence,
                is_mocked=mocked,
            ))

        # Audit log
        session.add(AuditLog(
            actor="system",
            action=f"screening_completed:verdict={risk.verdict}",
            entity=f"case:{case_id}",
        ))

        await session.commit()

    return {
        "case_id": case_id,
        "document_type": doc_type,
        "classification_confidence": gemini_result.get("classification_confidence"),
        "demographics": demographics,
        "checksum": checksum_result,
        "demographic_parity": demographic_result,
        "face_verification": face_match_data,
        "tamper": tamper_result.to_json(),
        "deepfake": deepfake_result.to_json(),
        "liveness": liveness_result.to_json(),
        "watchlist": watchlist_result.to_dict(),
        "risk_assessment": risk.to_dict(),
        "is_demo": is_demo_case,
        "demo_label": "DEMO ONLY — simulated AI excluded from scoring" if is_demo_case else None,
        "gemini_metadata": {
            "is_simulated": is_simulated,
            "is_demo": is_demo_case,
            "gemini_status": gemini_status,
            "latency_ms": gemini_result.get("latency_ms"),
            "model_used": gemini_result.get("model_used"),
            "db_photo_available": db_photo_path is not None,
        },
    }


# ---------------------------------------------------------------------------
# 4. GET /api/cases — Filterable dashboard case queue
# ---------------------------------------------------------------------------

@app.get("/cases", include_in_schema=False)
@app.get("/api/cases")
async def list_cases(
    request: Request,
    verdict: Optional[str] = Query(None, description="Filter by verdict: Green|Yellow|Red"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List screening cases with optional filters."""
    await _auth(request)  # audit P1 §2: require auth

    async with async_session() as session:
        query = select(ScreeningCase).order_by(ScreeningCase.timestamp.desc())

        if verdict:
            query = query.where(ScreeningCase.verdict == verdict)
        if status_filter:
            query = query.where(ScreeningCase.status == status_filter)

        query = query.limit(limit).offset(offset)
        result = await session.execute(query)
        cases = result.scalars().all()

    return {
        "cases": [c.to_dict() for c in cases],
        "count": len(cases),
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# 5. GET /api/cases/{id} — Full case report
# ---------------------------------------------------------------------------

@app.get("/cases/{case_id}", include_in_schema=False)
@app.get("/api/cases/{case_id}")
async def get_case(case_id: int, request: Request):
    """Get full case report with all module results and extracted fields."""
    await _auth(request)  # audit P1 §2: require auth

    async with async_session() as session:
        result = await session.execute(
            select(ScreeningCase).where(ScreeningCase.id == case_id)
        )
        case = result.scalar_one_or_none()

        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        # Load related data
        fields_result = await session.execute(
            select(ExtractedField).where(ExtractedField.case_id == case_id)
        )
        fields = fields_result.scalars().all()

        modules_result = await session.execute(
            select(ModuleResultDB).where(ModuleResultDB.case_id == case_id)
        )
        modules = modules_result.scalars().all()

        actions_result = await session.execute(
            select(OfficerAction).where(OfficerAction.case_id == case_id)
        )
        actions = actions_result.scalars().all()

        # Load citizen record if linked
        citizen_data = None
        if case.citizen_id:
            citizen_result = await session.execute(
                select(CitizenRegistry).where(CitizenRegistry.id == case.citizen_id)
            )
            citizen = citizen_result.scalar_one_or_none()
            if citizen:
                citizen_data = citizen.to_dict()

    # Demo flag: case relied on simulated Gemini data (real AI offline).
    # Computed from the persisted gemini module's is_mocked flag (set from
    # is_simulated at screening time). Local InsightFace fallback clears the
    # flag, so only truly simulated cases are labelled demo.
    is_demo = any(m.is_mocked for m in modules if m.module_name == "gemini_ai")
    # Also check the risk flags for the new DEMO marker (covers post-fallback demo cases)
    try:
        gem_mod = next((m for m in modules if m.module_name == "gemini_ai"), None)
        if gem_mod and gem_mod.raw_output:
            import json as _j
            _raw = _j.loads(gem_mod.raw_output) if isinstance(gem_mod.raw_output, str) else gem_mod.raw_output
            if isinstance(_raw, dict) and _raw.get("is_demo"):
                is_demo = True
    except Exception:
        pass

    return {
        "case": case.to_dict(),
        "citizen": citizen_data,
        "db_record_found": citizen_data is not None,
        "extracted_fields": [f.to_dict() for f in fields],
        "module_results": [m.to_dict() for m in modules],
        "officer_actions": [a.to_dict() for a in actions],
        "is_demo": is_demo,
        "demo_label": "DEMO ONLY — simulated AI excluded from scoring" if is_demo else None,
    }


# ---------------------------------------------------------------------------
# 6. POST /api/cases/{id}/override — Officer decision
# ---------------------------------------------------------------------------

@app.post("/cases/{case_id}/override", include_in_schema=False)
@app.post("/api/cases/{case_id}/override")
async def override_case(case_id: int, req: OverrideRequest, request: Request):
    """Record officer decision (clear/deny/escalate) with mandatory reason."""
    if req.action not in ("clear", "deny", "escalate"):
        raise HTTPException(
            status_code=400,
            detail="Action must be one of: clear, deny, escalate",
        )

    if not req.reason or len(req.reason.strip()) < 3:
        raise HTTPException(
            status_code=400,
            detail="Reason is mandatory (minimum 3 characters)",
        )

    # Auth — mandatory (audit P1 §1)
    officer = await _auth(request)
    officer_id = int(officer["sub"])
    username = officer.get("username", "unknown")

    async with async_session() as session:
        # Verify case exists
        result = await session.execute(
            select(ScreeningCase).where(ScreeningCase.id == case_id)
        )
        case = result.scalar_one_or_none()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        # Record officer action
        session.add(OfficerAction(
            case_id=case_id,
            officer_id=officer_id,
            action=req.action,
            reason=req.reason.strip(),
        ))

        # Update case status
        case.status = "decided"

        # Audit log
        session.add(AuditLog(
            actor=username,
            action=f"officer_override:{req.action}",
            entity=f"case:{case_id}",
        ))

        await session.commit()

    return {
        "status": "ok",
        "case_id": case_id,
        "action": req.action,
        "message": f"Case {case_id} marked as '{req.action}' by {username}",
    }


# ---------------------------------------------------------------------------
# 7. GET /api/audit — Append-only audit trail
# ---------------------------------------------------------------------------

@app.get("/audit", include_in_schema=False)
@app.get("/api/audit")
async def list_audit(
    request: Request,
    actor: Optional[str] = Query(None),
    entity: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """View the append-only audit trail."""
    await _auth(request)  # audit P1 §2: require auth

    async with async_session() as session:
        query = select(AuditLog).order_by(AuditLog.timestamp.desc())

        if actor:
            query = query.where(AuditLog.actor == actor)
        if entity:
            query = query.where(AuditLog.entity.contains(entity))

        query = query.limit(limit).offset(offset)
        result = await session.execute(query)
        logs = result.scalars().all()

    return {
        "audit_logs": [l.to_dict() for l in logs],
        "count": len(logs),
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# 8. Citizen Registry management (supervisor-managed reference database)
# ---------------------------------------------------------------------------

_DOC_TYPES = {"aadhaar", "pan", "voter_id", "passport"}
_REGISTRY_FACES_DIR = _PROJECT_ROOT / "samples" / "faces" / "uploads"


def _require_role(officer: dict, role: str) -> None:
    """Raise 403 unless the authenticated officer has the given role."""
    if officer.get("role") != role:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied: '{role}' role required",
        )


def _normalize_doc_number(number: str) -> str:
    """Normalize a document number the same way screening lookups do."""
    return (number or "").strip().replace(" ", "").replace("-", "").upper()


@app.get("/citizens", include_in_schema=False)
@app.get("/api/citizens")
async def list_citizens(
    request: Request,
    q: Optional[str] = Query(None, description="Search by name or document number"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List registered citizens (reference profiles for screening)."""
    await _auth(request)  # any authenticated role may view the registry

    async with async_session() as session:
        query = select(CitizenRegistry).order_by(CitizenRegistry.id.asc())

        if q and q.strip():
            needle = f"%{q.strip()}%"
            query = query.where(
                CitizenRegistry.full_name.ilike(needle)
                | CitizenRegistry.document_number.ilike(needle)
            )

        total = len((await session.execute(query)).scalars().all())
        query = query.limit(limit).offset(offset)
        result = await session.execute(query)
        citizens = result.scalars().all()

    return {
        "citizens": [c.to_dict() for c in citizens],
        "count": total,
        "limit": limit,
        "offset": offset,
    }


@app.post("/citizens", include_in_schema=False)
@app.post("/api/citizens")
async def create_citizen(
    request: Request,
    document_type: str = Form(...),
    document_number: str = Form(...),
    full_name: str = Form(...),
    date_of_birth: str = Form(None),
    gender: str = Form(None),
    address: str = Form(None),
    father_or_spouse_name: str = Form(None),
    photo: UploadFile = File(None),
):
    """Register a new citizen record (supervisor only)."""
    officer = await _auth(request)
    _require_role(officer, "supervisor")
    username = officer.get("username", "unknown")

    # --- validate input ---
    doc_type = document_type.strip().lower()
    if doc_type not in _DOC_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"document_type must be one of: {sorted(_DOC_TYPES)}",
        )

    doc_number = _normalize_doc_number(document_number)
    if not doc_number:
        raise HTTPException(status_code=400, detail="document_number is required")

    name = full_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="full_name is required")

    if gender and gender.strip().upper() not in ("M", "F", "OTHER"):
        raise HTTPException(status_code=400, detail="gender must be M, F or Other")

    # --- optional photo upload ---
    photo_uri = None
    if photo and photo.filename:
        _REGISTRY_FACES_DIR.mkdir(parents=True, exist_ok=True)
        suffix = Path(photo.filename).suffix.lower() or ".png"
        if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
            suffix = ".png"
        photo_bytes = await photo.read()
        if len(photo_bytes) > 5_000_000:
            raise HTTPException(status_code=400, detail="Photo too large (max 5 MB)")
        rel = Path("samples") / "faces" / "uploads" / f"{uuid.uuid4().hex}{suffix}"
        (_PROJECT_ROOT / rel).write_bytes(photo_bytes)
        photo_uri = rel.as_posix()

    async with async_session() as session:
        # unique document number (normalized comparison)
        existing = await session.execute(
            select(CitizenRegistry).where(
                CitizenRegistry.document_number == doc_number
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail=f"A citizen with document number {doc_number} already exists",
            )

        citizen = CitizenRegistry(
            document_type=doc_type,
            document_number=doc_number,
            full_name=name,
            date_of_birth=(date_of_birth or "").strip() or None,
            gender=(gender or "").strip().upper() or None,
            address=(address or "").strip() or None,
            father_or_spouse_name=(father_or_spouse_name or "").strip() or None,
            photo_uri=photo_uri,
        )
        session.add(citizen)
        await session.flush()
        citizen_id = citizen.id

        # Audit log
        session.add(AuditLog(
            actor=username,
            action="citizen_registered",
            entity=f"citizen:{citizen_id}:{doc_type}:{doc_number}",
        ))
        await session.commit()

    return {
        "status": "ok",
        "citizen": citizen.to_dict(),
        "message": f"Registered {name} ({doc_type.upper()})",
    }


@app.delete("/citizens/{citizen_id}", include_in_schema=False)
@app.delete("/api/citizens/{citizen_id}")
async def delete_citizen(citizen_id: int, request: Request):
    """Remove a citizen record from the registry (supervisor only)."""
    officer = await _auth(request)
    _require_role(officer, "supervisor")
    username = officer.get("username", "unknown")

    async with async_session() as session:
        result = await session.execute(
            select(CitizenRegistry).where(CitizenRegistry.id == citizen_id)
        )
        citizen = result.scalar_one_or_none()
        if not citizen:
            raise HTTPException(status_code=404, detail="Citizen not found")

        detail = f"{citizen.full_name}:{citizen.document_type}:{citizen.document_number}"
        await session.delete(citizen)

        session.add(AuditLog(
            actor=username,
            action="citizen_removed",
            entity=f"citizen:{citizen_id}:{detail}",
        ))
        await session.commit()

    return {
        "status": "ok",
        "deleted_id": citizen_id,
        "message": f"Removed {detail} from the registry",
    }


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", include_in_schema=False)
@app.get("/api/health")
async def health():
    """System health check."""
    from backend.database import get_engine_info
    return {
        "status": "healthy",
        "version": "0.1.0",
        "database": get_engine_info(),
    }

# ---------------------------------------------------------------------------
# SPA Fallback (Must be at the very bottom)
# ---------------------------------------------------------------------------

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """Serve the built React SPA — real static files when present, otherwise index.html (SPA fallback).

    IMPORTANT: this catch-all must stay registered AFTER the /api and /evidence
    routes so those are matched first (a "/" StaticFiles mount would swallow them).
    """
    from fastapi.responses import FileResponse

    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")

    if _FRONTEND_DIR.exists():
        # Serve real static assets (JS/CSS/images) if the file exists.
        if full_path:
            file_candidate = (_FRONTEND_DIR / full_path).resolve()
            # Guard against path traversal outside the frontend dist directory.
            if file_candidate.is_file() and _FRONTEND_DIR in file_candidate.parents:
                return FileResponse(str(file_candidate))

        # SPA fallback: route any unmatched path to index.html.
        index_path = _FRONTEND_DIR / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))

    raise HTTPException(status_code=404, detail="Frontend not built")

