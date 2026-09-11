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


def _create_token(officer_id: int, username: str, role: str, unit: str = "BORDER_UNIT_1") -> str:
    """Create a JWT token for an authenticated officer."""
    import uuid as _uuid
    jti = _uuid.uuid4().hex
    if _HAS_PYJWT:
        payload = {
            "sub": str(officer_id),
            "username": username,
            "role": role,
            "unit": unit,
            "jti": jti,
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
            "unit": unit,
            "jti": jti,
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


def collect_provenance(file_hashes: Optional[dict] = None, extra: Optional[dict] = None) -> tuple[dict, str]:
    """Collect immutable provenance for a screening decision and sign it.

    Returns (provenance_dict, signature).
    Provenance includes: code version, model versions/thresholds, dependency versions,
    input checksums, and config. Signed with HMAC-SHA256 using JWT secret.
    """
    import hashlib as _hashlib
    import hmac as _hmac
    # Code version
    try:
        import subprocess as _sp
        git_commit = _sp.check_output(["git", "rev-parse", "HEAD"], cwd=str(_PROJECT_ROOT), text=True).strip()[:12]
    except Exception:
        git_commit = "unknown"
    # Model / threshold versions
    try:
        from pipeline.face_match import MATCH_THRESHOLD as _face_thr
    except Exception:
        _face_thr = 0.55
    try:
        from pipeline.tamper import COPY_FLOOR as _copy_floor, COPY_SAT as _copy_sat  # type: ignore
    except Exception:
        _copy_floor, _copy_sat = 10, 90
    # Dependency versions
    deps = {}
    for pkg in ["opencv-python-headless", "insightface", "mediapipe", "numpy", "onnxruntime", "fastapi", "sqlalchemy"]:
        try:
            import importlib.metadata as _im
            deps[pkg] = _im.version(pkg)
        except Exception:
            try:
                import pkg_resources as _pr  # type: ignore
                deps[pkg] = _pr.get_distribution(pkg).version
            except Exception:
                deps[pkg] = "unknown"
    prov = {
        "code_version": git_commit,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "models": {
            "face_match": {"name": "insightface/buffalo_l", "threshold": _face_thr, "providers": "CPUExecutionProvider"},
            "liveness": {"name": "mediapipe/face_landmarker", "model": "face_landmarker.task"},
            "tamper": {"ela_threshold": 8.0, "copy_floor": _copy_floor, "copy_sat": _copy_sat},
            "deepfake": {"method": "fft_frequency_artifact_heuristic"},
            "gemini": {"model": os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")},
            "risk_engine": {"version": "1.0", "rules": "Green<0.35<Yellow<0.65<Red"},
        },
        "thresholds": {
            "face_match": _face_thr,
            "tamper_high": 0.7,
            "tamper_moderate": 0.4,
            "deepfake_high": 0.7,
            "liveness": 0.45,
        },
        "dependencies": deps,
        "config": {
            "demo_mode": _DEMO_MODE,
            "jwt_expiry_hours": _JWT_EXPIRY_HOURS,
        },
        "input_hashes": file_hashes or {},
    }
    if extra:
        prov.update(extra)
    # Sign with HMAC-SHA256
    try:
        payload = json.dumps(prov, sort_keys=True).encode()
        sig = _hmac.new(_JWT_SECRET.encode(), payload, _hashlib.sha256).hexdigest()
    except Exception:
        sig = ""
    return prov, sig


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

# Evidence directory (no longer publicly mounted — served via authenticated endpoints below)
_EVIDENCE_DIR = _PROJECT_ROOT / "samples" / "evidence"
_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

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

    # Orphan biometric file check (retention hygiene)
    try:
        uploads_dir = (_PROJECT_ROOT / "samples" / "faces" / "uploads").resolve()
        if uploads_dir.is_dir():
            all_files = [p.name for p in uploads_dir.iterdir() if p.is_file()]
            if all_files:
                async with async_session() as session:
                    from sqlalchemy import select as _select
                    r = await session.execute(_select(CitizenRegistry.photo_uri))
                    referenced = {Path(uri).name for uri, in r.all() if uri}
                orphans = [f for f in all_files if f not in referenced]
                if orphans:
                    print(f"[startup] WARNING: Found {len(orphans)} orphan biometric file(s) in {uploads_dir}: {orphans} — run POST /api/citizens/orphans/cleanup as supervisor to securely erase")
                else:
                    print(f"[startup] Biometric retention check: no orphan files ({len(all_files)} file(s) all referenced)")
    except Exception as e:
        print(f"[startup] Orphan check warning: {e}")


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
    version: Optional[int] = None  # for optimistic locking (client's expected version)


# ---------------------------------------------------------------------------
# Auth helper — extract officer from Bearer token
# ---------------------------------------------------------------------------

async def _auth(request) -> dict:
    """Extract officer info from Authorization header and enrich with fresh DB state."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = auth[7:]
    payload = _decode_token(token)
    # Enrich with current DB state for unit/role (handles old tokens missing unit)
    try:
        async with async_session() as session:
            res = await session.execute(select(Officer).where(Officer.id == int(payload.get("sub", 0))))
            off = res.scalar_one_or_none()
            if off:
                payload["unit"] = getattr(off, "unit", None) or payload.get("unit") or "BORDER_UNIT_1"
                payload["role"] = off.role or payload.get("role", "officer")
                payload["username"] = off.username
    except Exception:
        pass
    payload.setdefault("unit", "BORDER_UNIT_1")
    payload.setdefault("role", "officer")
    return payload


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

    token = _create_token(officer.id, officer.username, officer.role, getattr(officer, "unit", "BORDER_UNIT_1") or "BORDER_UNIT_1")

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
    # Enriched audit context
    import hashlib, uuid as _uuid
    request_id = request.headers.get("X-Request-ID") or _uuid.uuid4().hex
    # Device/location from headers + client IP
    user_agent = request.headers.get("User-Agent", "")[:300]
    xff = request.headers.get("X-Forwarded-For", "")
    x_real_ip = request.headers.get("X-Real-IP", "")
    client_host = request.client.host if request.client else ""
    device_info = f"UA:{user_agent} | IP:{client_host} | XFF:{xff} | XRealIP:{x_real_ip} | unit:{officer.get('unit','')}"

    import tempfile

    doc_bytes = await document_image.read()
    # Hash input files for audit trail
    doc_hash = hashlib.sha256(doc_bytes).hexdigest()
    file_hashes = {"document": doc_hash}
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png", prefix="screen_doc_") as tmp:
        tmp.write(doc_bytes)
        doc_tmp = Path(tmp.name)

    live_tmp = None
    if live_capture and live_capture.filename:
        live_bytes = await live_capture.read()
        file_hashes["live_capture"] = hashlib.sha256(live_bytes).hexdigest()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png", prefix="screen_live_") as tmp:
            tmp.write(live_bytes)
            live_tmp = Path(tmp.name)

    # Frame burst for liveness (preferred over single still)
    live_frame_tmps = []
    if live_frames:
        for i, f in enumerate(live_frames):
            if f and f.filename:
                fb = await f.read()
                file_hashes[f"live_frame_{i}"] = hashlib.sha256(fb).hexdigest()
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png", prefix=f"screen_burst_{i}_") as tmp:
                    tmp.write(fb)
                    live_frame_tmps.append(Path(tmp.name))

    burst = [str(p) for p in live_frame_tmps] or (
        [str(live_tmp)] if live_tmp else None
    )

    # Resolve officer unit for location scoping (least-privilege)
    officer_unit = officer.get("unit") or "BORDER_UNIT_1"
    if not officer.get("unit"):
        try:
            async with async_session() as _sess:
                _res = await _sess.execute(select(Officer).where(Officer.id == officer_id))
                _off = _res.scalar_one_or_none()
                if _off and getattr(_off, "unit", None):
                    officer_unit = _off.unit
        except Exception:
            pass
    try:
        audit_context = {
            "officer_id": officer_id,
            "username": officer.get("username", "unknown"),
            "session_id": officer.get("jti") or officer.get("session_id") or "",
            "request_id": request_id,
            "device_info": device_info,
            "file_hashes": file_hashes,
        }
        result = await _run_screening_pipeline(doc_tmp, live_tmp, officer_id, officer_unit, burst, audit_context)
    finally:
        # Cleanup temp files
        doc_tmp.unlink(missing_ok=True)
        if live_tmp:
            live_tmp.unlink(missing_ok=True)
        for p in live_frame_tmps:
            p.unlink(missing_ok=True)

    elapsed = (time.perf_counter() - start_time) * 1000
    result["total_latency_ms"] = round(elapsed, 1)
    result["request_id"] = request_id
    result["session_id"] = officer.get("jti") or ""
    # Also expose request_id as a response header for tracing (if using JSONResponse, set header)
    try:
        from fastapi.responses import JSONResponse
        # If the caller expects a dict, FastAPI will still handle JSONResponse
        # We keep returning dict for simplicity, but also ensure request_id is in the JSON
        pass
    except Exception:
        pass

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
    officer_unit: str = "BORDER_UNIT_1",
    live_burst: Optional[List[str]] = None,
    audit_context: Optional[dict] = None,
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
        # Visible-field OCR often misses the type; fall back to MRZ document_type
        if not ocr_type:
            mrz_type = (ocr_result.raw_output or {}).get("mrz", {}).get("fields", {}).get("document_type")
            if mrz_type:
                mt = str(mrz_type).strip().upper()
                if mt == "P":
                    ocr_type = "passport"
                elif mt.lower() in ("aadhaar", "pan", "voter_id", "passport"):
                    ocr_type = mt.lower()
                else:
                    ocr_type = mt.lower()
        doc_type = (ocr_type or "unknown").strip().lower()

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
    # --- Local 3-way DB enrichment: compute Doc vs DB / Live vs DB via InsightFace ---
    if db_photo_path:
        need_doc_db = face_match_data.get("doc_vs_db_match") is None
        need_live_db = face_match_data.get("live_vs_db_match") is None and live_str is not None
        if need_doc_db or need_live_db:
            enrich_tasks = []
            if need_doc_db:
                enrich_tasks.append(loop.run_in_executor(None, _run_local_face, str(doc_path), db_photo_path, False))
            else:
                enrich_tasks.append(None)
            if need_live_db:
                enrich_tasks.append(loop.run_in_executor(None, _run_local_face, live_str, db_photo_path, False))
            else:
                enrich_tasks.append(None)
            try:
                results = []
                for t in enrich_tasks:
                    if t is None:
                        results.append(None)
                    else:
                        results.append(await t)
                doc_db_res, live_db_res = results[0], results[1]
                if doc_db_res is not None and doc_db_res.status == "ok":
                    raw = doc_db_res.raw_output or {}
                    face_match_data["doc_vs_db_match"] = bool(raw.get("match"))
                    face_match_data["doc_vs_db_similarity"] = float(raw.get("similarity")) if raw.get("similarity") is not None else None
                    gemini_result["three_way_face_match"] = face_match_data
                if live_db_res is not None and live_db_res.status == "ok":
                    raw = live_db_res.raw_output or {}
                    face_match_data["live_vs_db_match"] = bool(raw.get("match"))
                    face_match_data["live_vs_db_similarity"] = float(raw.get("similarity")) if raw.get("similarity") is not None else None
                    gemini_result["three_way_face_match"] = face_match_data
                if (doc_db_res is not None and doc_db_res.status == "ok") or (live_db_res is not None and live_db_res.status == "ok"):
                    extra = []
                    if doc_db_res is not None and doc_db_res.status == "ok":
                        extra.append(f"Doc vs DB local {doc_db_res.raw_output.get('similarity'):.3f}")
                    if live_db_res is not None and live_db_res.status == "ok":
                        extra.append(f"Live vs DB local {live_db_res.raw_output.get('similarity'):.3f}")
                    if extra:
                        face_match_data["visual_reasoning"] = (face_match_data.get("visual_reasoning") or "") + " | " + ", ".join(extra)
                        gemini_result["three_way_face_match"] = face_match_data
            except Exception as e:
                print(f"[enrich] DB enrich exception {e}")

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
    # If face was enriched via real local InsightFace, keep it even in demo
    # mode (real biometrics, not simulated), but still label the case demo.
    is_demo_case = bool(is_simulated)
    if is_demo_case and not face_is_real_via_local:
        face_sim = None
        face_match_bool = None
        face_status_for_risk = "inconclusive"
        gemini_face_for_risk = None
        gemini_tamper_for_risk = None
    elif is_demo_case and face_is_real_via_local:
        # Real local face is available — include it, but still exclude Gemini tamper
        face_status_for_risk = "ok" if face_sim is not None else "inconclusive"
        gemini_face_for_risk = face_match_data
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

    # Collect provenance for reproducibility (signed)
    _prov_extra = {
        "officer_id": officer_id,
        "officer_unit": officer_unit,
        "document_type": doc_type,
        "citizen_id": citizen_id,
        "verdict": risk.verdict,
        "risk_score": risk.risk_score,
    }
    _file_hashes = {}
    try:
        if audit_context and audit_context.get("file_hashes"):
            _file_hashes = audit_context["file_hashes"]
    except Exception:
        pass
    provenance, provenance_sig = collect_provenance(_file_hashes, _prov_extra)

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
            unit=officer_unit,
            provenance=json.dumps(provenance),
            provenance_signature=provenance_sig,
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

        # Audit log — attributed to the initiating officer with full traceability
        audit_ctx = audit_context or {}
        actor = audit_ctx.get("username") or f"officer:{officer_id}"
        # Include hashes and device info in the action for easy investigation
        file_hashes_str = ""
        try:
            fh = audit_ctx.get("file_hashes") or {}
            if fh:
                file_hashes_str = f" files:{json.dumps({k: v[:12] for k, v in fh.items()})}"
        except Exception:
            pass
        session.add(AuditLog(
            actor=actor,
            action=f"screening_completed:verdict={risk.verdict} unit:{officer_unit}{file_hashes_str}",
            entity=f"case:{case_id}",
            officer_id=audit_ctx.get("officer_id") or officer_id,
            session_id=audit_ctx.get("session_id") or "",
            request_id=audit_ctx.get("request_id") or "",
            device_info=audit_ctx.get("device_info") or "",
            file_hashes=json.dumps(audit_ctx.get("file_hashes") or {}),
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
        "provenance": provenance,
        "provenance_signature": provenance_sig,
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
    """List screening cases with least-privilege scoping."""
    officer = await _auth(request)

    async with async_session() as session:
        query = select(ScreeningCase).order_by(ScreeningCase.timestamp.desc())

        # Least-privilege: officer sees own cases only; supervisor sees unit; auditor sees all
        if officer.get("role") == "officer":
            query = query.where(ScreeningCase.officer_id == int(officer["sub"]))
        elif officer.get("role") == "supervisor":
            # Supervisor sees all cases in their unit (including own)
            unit = officer.get("unit") or "BORDER_UNIT_1"
            query = query.where(
                (ScreeningCase.unit == unit) | (ScreeningCase.unit.is_(None))  # handle old cases with NULL unit
            )
        elif officer.get("role") == "auditor":
            pass  # auditor sees all cases across units
        else:
            # Fallback: least privilege
            query = query.where(ScreeningCase.officer_id == int(officer["sub"]))

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
    """Get full case report with least-privilege access control."""
    officer = await _auth(request)

    async with async_session() as session:
        result = await session.execute(
            select(ScreeningCase).where(ScreeningCase.id == case_id)
        )
        case = result.scalar_one_or_none()

        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        # Least-privilege: check ownership / unit / auditor
        role = officer.get("role", "officer")
        officer_id = int(officer.get("sub", 0))
        officer_unit = officer.get("unit") or "BORDER_UNIT_1"
        if role == "officer" and case.officer_id != officer_id:
            raise HTTPException(status_code=403, detail="Access denied: case belongs to another officer")
        elif role == "supervisor" and case.unit and case.unit != officer_unit:
            # Supervisor can only view cases in their unit (allow old cases with NULL unit for backward compat)
            raise HTTPException(status_code=403, detail="Access denied: case outside your unit")
        # auditor can view all

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


@app.get("/api/cases/{case_id}/provenance", include_in_schema=False)
@app.get("/api/cases/{case_id}/provenance/verify", include_in_schema=False)
async def get_provenance(case_id: int, request: Request):
    """Return the signed provenance for a case and verify its integrity."""
    officer = await _auth(request)
    # Check access to the case first
    async with async_session() as session:
        result = await session.execute(select(ScreeningCase).where(ScreeningCase.id == case_id))
        case = result.scalar_one_or_none()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        # Least-privilege check
        role = officer.get("role", "officer")
        officer_id = int(officer.get("sub", 0))
        officer_unit = officer.get("unit") or "BORDER_UNIT_1"
        if role == "officer" and case.officer_id != officer_id:
            raise HTTPException(status_code=403, detail="Access denied")
        if role == "supervisor" and case.unit and case.unit != officer_unit:
            raise HTTPException(status_code=403, detail="Access denied: case outside your unit")
        # auditor can view all

        if not case.provenance:
            return {"case_id": case_id, "provenance": None, "verified": False, "reason": "No provenance recorded (case created before provenance tracking)"}
        try:
            prov = json.loads(case.provenance) if isinstance(case.provenance, str) else case.provenance
        except Exception:
            prov = case.provenance
        # Verify signature
        verified = False
        reason = "unknown"
        try:
            import hmac as _hmac, hashlib as _hashlib
            payload = json.dumps(prov, sort_keys=True).encode() if isinstance(prov, dict) else str(prov).encode()
            expected = _hmac.new(_JWT_SECRET.encode(), payload, _hashlib.sha256).hexdigest()
            stored = case.provenance_signature or ""
            verified = _hmac.compare_digest(expected, stored)
            reason = "signature matches" if verified else "signature mismatch"
        except Exception as e:
            reason = f"verification error: {e}"
        return {
            "case_id": case_id,
            "provenance": prov,
            "provenance_signature": case.provenance_signature,
            "verified": verified,
            "verification_reason": reason,
            "is_demo": any(m.is_mocked for m in (await session.execute(select(ModuleResultDB).where(ModuleResultDB.case_id == case_id))).scalars().all() if m.module_name == "gemini_ai"),
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

        # Least-privilege: check case ownership / unit scope / auditor read-only
        role = officer.get("role", "officer")
        officer_unit = officer.get("unit") or "BORDER_UNIT_1"
        if role == "auditor":
            raise HTTPException(status_code=403, detail="Access denied: auditor role is read-only, cannot override cases")
        if role == "officer" and case.officer_id != officer_id:
            raise HTTPException(status_code=403, detail="Access denied: cannot act on another officer's case")
        if role == "supervisor" and case.unit and case.unit != officer_unit:
            raise HTTPException(status_code=403, detail="Access denied: case outside your unit")

        # State transition & optimistic locking
        # 1. Already decided? -> 409 Conflict (integrity)
        if case.status == "decided":
            raise HTTPException(status_code=409, detail="Conflict: case already has a final decision and cannot be modified")
        # 2. Optimistic locking: if client supplied version/If-Match, verify it matches current
        client_version = req.version
        # Also support If-Match header as alternative
        if_match = request.headers.get("If-Match")
        if if_match is not None:
            try:
                client_version = int(if_match.strip().strip('"'))
            except ValueError:
                pass
        current_version = getattr(case, "version", 0) or 0
        if client_version is not None and int(client_version) != int(current_version):
            raise HTTPException(
                status_code=409,
                detail=f"Conflict: case was modified by another officer (expected version {client_version}, current {current_version}). Please refresh and retry.",
            )
        # 3. Supervisor approval for final denial
        if req.action == "deny" and role == "officer":
            raise HTTPException(
                status_code=403,
                detail="Access denied: final denial requires supervisor approval — please use 'escalate' to send to supervisor",
            )
        # 4. Valid state transitions
        # pending_review -> clear/deny (supervisor) or escalate (officer)
        # escalated -> clear/deny (supervisor only)
        if case.status == "escalated" and role == "officer":
            raise HTTPException(status_code=403, detail="Access denied: escalated cases can only be decided by a supervisor")

        # Record officer action
        session.add(OfficerAction(
            case_id=case_id,
            officer_id=officer_id,
            action=req.action,
            reason=req.reason.strip(),
        ))

        # Update case status with state machine
        if req.action == "escalate":
            case.status = "escalated"
        else:  # clear or deny
            case.status = "decided"
        # Optimistic locking: bump version
        try:
            case.version = int(current_version) + 1
        except Exception:
            case.version = 1

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
    """View the append-only audit trail — auditor role only (least-privilege)."""
    officer = await _auth(request)
    if officer.get("role") != "auditor":
        raise HTTPException(status_code=403, detail="Access denied: auditor role required to view audit logs")

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
    """List registered citizens with least-privilege scoping."""
    officer = await _auth(request)
    # Officer can only view citizens linked to their own cases; supervisor/auditor can view all
    if officer.get("role") == "officer":
        async with async_session() as session:
            # Get citizen IDs from officer's own cases
            cases_res = await session.execute(
                select(ScreeningCase.citizen_id).where(
                    (ScreeningCase.officer_id == int(officer["sub"])) & (ScreeningCase.citizen_id.is_not(None))
                )
            )
            allowed_ids = {row[0] for row in cases_res.all()}
            if not allowed_ids:
                return {"citizens": [], "count": 0, "limit": limit, "offset": offset}
            query = select(CitizenRegistry).where(CitizenRegistry.id.in_(allowed_ids)).order_by(CitizenRegistry.id.asc())
            if q and q.strip():
                needle = f"%{q.strip()}%"
                query = query.where(
                    CitizenRegistry.full_name.ilike(needle) | CitizenRegistry.document_number.ilike(needle)
                )
            # Still apply q filter if needed, but already filtered to allowed_ids
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
    # supervisor and auditor can view all (with optional search)

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
        # Capture photo info before deletion for secure erasure and audit
        photo_uri = citizen.photo_uri
        photo_path = None
        if photo_uri:
            # Only delete files in the uploads directory (seeded samples/faces/*.png are shared)
            try:
                candidate = (_PROJECT_ROOT / photo_uri).resolve()
                # Ensure it's inside the uploads directory to avoid deleting shared samples
                uploads_dir = (_PROJECT_ROOT / "samples" / "faces" / "uploads").resolve()
                if uploads_dir in candidate.parents or candidate.parent.resolve() == uploads_dir:
                    photo_path = candidate
                elif "uploads" in photo_uri:
                    # Fallback: treat any uploads path as deletable
                    photo_path = candidate
            except Exception:
                photo_path = None

        await session.delete(citizen)

        session.add(AuditLog(
            actor=username,
            action="citizen_removed",
            entity=f"citizen:{citizen_id}:{detail}",
        ))
        # Record retention/deletion event for biometric data
        if photo_uri:
            session.add(AuditLog(
                actor=username,
                action="biometric_retention:deleted",
                entity=f"citizen:{citizen_id}:photo:{photo_uri}",
            ))
        await session.commit()

    # Securely delete the biometric file outside the transaction (best-effort, no rollback needed)
    if photo_path and photo_path.is_file():
        try:
            # Cryptographic erasure: overwrite with zeros before unlinking
            size = photo_path.stat().st_size
            with open(photo_path, "r+b") as f:
                f.write(b"\x00" * size)
                f.flush()
                try:
                    import os as _os
                    _os.fsync(f.fileno())
                except Exception:
                    pass
            photo_path.unlink()
        except FileNotFoundError:
            pass
        except Exception as e:
            # Log but don't fail the request — the DB record is already gone
            print(f"[retention] failed to securely delete {photo_path}: {e}")

    return {
        "status": "ok",
        "deleted_id": citizen_id,
        "message": f"Removed {detail} from the registry",
        "photo_deleted": bool(photo_path and not (photo_path.is_file() if photo_path else True)),
        "photo_uri": photo_uri,
    }


def _find_orphan_biometric_files() -> list[str]:
    """Scan uploads for files not referenced by any CitizenRegistry.photo_uri."""
    uploads_dir = (_PROJECT_ROOT / "samples" / "faces" / "uploads").resolve()
    if not uploads_dir.is_dir():
        return []
    # Collect all referenced photo URIs
    # This is called from async context, so we need to handle both sync and async
    return []  # placeholder for sync call; actual async version below


async def _find_orphans_async() -> tuple[list[str], list[str]]:
    """Async helper to find orphan files: returns (orphans, all_files)."""
    uploads_dir = (_PROJECT_ROOT / "samples" / "faces" / "uploads").resolve()
    if not uploads_dir.is_dir():
        return [], []
    all_files = [p.name for p in uploads_dir.iterdir() if p.is_file()]
    if not all_files:
        return [], []
    async with async_session() as session:
        result = await session.execute(select(CitizenRegistry.photo_uri))
        referenced = {r[0] for r in result.all() if r[0]}
    # Extract just the filenames from referenced URIs
    referenced_names = set()
    for uri in referenced:
        try:
            referenced_names.add(Path(uri).name)
        except Exception:
            pass
    orphans = [f for f in all_files if f not in referenced_names]
    return orphans, all_files


@app.get("/api/citizens/orphans", include_in_schema=False)
@app.get("/api/citizens/orphans/check", include_in_schema=False)
async def check_orphan_files(request: Request):
    """List orphan biometric files not linked to any citizen (supervisor/auditor only)."""
    officer = await _auth(request)
    if officer.get("role") not in ("supervisor", "auditor"):
        raise HTTPException(status_code=403, detail="Access denied: supervisor or auditor role required")
    orphans, all_files = await _find_orphans_async()
    return {
        "orphans": orphans,
        "orphan_count": len(orphans),
        "total_files": len(all_files),
        "uploads_dir": str(_PROJECT_ROOT / "samples" / "faces" / "uploads"),
    }


@app.post("/api/citizens/orphans/cleanup", include_in_schema=False)
async def cleanup_orphan_files(request: Request):
    """Securely delete orphan biometric files (supervisor only) and log the action."""
    officer = await _auth(request)
    _require_role(officer, "supervisor")
    orphans, _ = await _find_orphans_async()
    deleted = []
    failed = []
    uploads_dir = (_PROJECT_ROOT / "samples" / "faces" / "uploads").resolve()
    for fname in orphans:
        p = (uploads_dir / fname).resolve()
        # Safety: ensure it's still inside uploads
        if uploads_dir not in p.parents and p.parent.resolve() != uploads_dir:
            failed.append(fname)
            continue
        try:
            if p.is_file():
                size = p.stat().st_size
                with open(p, "r+b") as f:
                    f.write(b"\x00" * size)
                    f.flush()
                    try:
                        import os as _os
                        _os.fsync(f.fileno())
                    except Exception:
                        pass
                p.unlink()
                deleted.append(fname)
        except Exception as e:
            failed.append(f"{fname}: {e}")
    # Audit log
    async with async_session() as session:
        session.add(AuditLog(
            actor=officer.get("username", "unknown"),
            action="biometric_retention:orphan_cleanup",
            entity=f"orphans_deleted:{len(deleted)} failed:{len(failed)}",
        ))
        await session.commit()
    return {"deleted": deleted, "deleted_count": len(deleted), "failed": failed}


# ---------------------------------------------------------------------------
# 9. Evidence files — authenticated + expiring links (no public /evidence)
# ---------------------------------------------------------------------------

def _evidence_token_for(filename: str, officer_id: int, expires_in: int = 300) -> str:
    """Create a short-lived signed token for an evidence file."""
    if _HAS_PYJWT:
        payload = {
            "sub": str(officer_id),
            "filename": filename,
            "exp": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
            "iat": datetime.now(timezone.utc),
            "type": "evidence",
        }
        return pyjwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)
    else:
        import base64
        payload = json.dumps({
            "sub": str(officer_id),
            "filename": filename,
            "exp": (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).timestamp(),
        })
        return base64.b64encode(payload.encode()).decode()

def _verify_evidence_token(token: str) -> dict:
    """Verify an evidence token and return its payload."""
    if _HAS_PYJWT:
        try:
            payload = pyjwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
            if payload.get("type") != "evidence":
                raise HTTPException(status_code=403, detail="Invalid evidence token type")
            return payload
        except pyjwt.ExpiredSignatureError:
            raise HTTPException(status_code=403, detail="Evidence link expired")
        except pyjwt.InvalidTokenError as e:
            raise HTTPException(status_code=403, detail=f"Invalid evidence token: {e}")
    else:
        import base64
        try:
            payload = json.loads(base64.b64decode(token.encode()).decode())
            if payload.get("exp", 0) < datetime.now(timezone.utc).timestamp():
                raise HTTPException(status_code=403, detail="Evidence link expired")
            return payload
        except Exception as e:
            raise HTTPException(status_code=403, detail=f"Invalid evidence token: {e}")


async def _check_evidence_access(filename: str, officer: dict) -> None:
    """Verify the officer has access to the case owning this evidence file."""
    # Sanitize filename to prevent path traversal
    safe_name = Path(filename).name
    if safe_name != filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    # Find which case(s) own this evidence file
    async with async_session() as session:
        result = await session.execute(
            select(ModuleResultDB).where(ModuleResultDB.evidence_uri.contains(safe_name))
        )
        modules = result.scalars().all()
        if not modules:
            raise HTTPException(status_code=404, detail="Evidence file not found")
        # Check if officer has access to at least one owning case
        for mod in modules:
            case_res = await session.execute(select(ScreeningCase).where(ScreeningCase.id == mod.case_id))
            case = case_res.scalar_one_or_none()
            if not case:
                continue
            role = officer.get("role", "officer")
            officer_id = int(officer.get("sub", 0))
            officer_unit = officer.get("unit") or "BORDER_UNIT_1"
            if role == "auditor":
                return  # auditor can access all
            if role == "officer" and case.officer_id == officer_id:
                return
            if role == "supervisor" and (not case.unit or case.unit == officer_unit):
                return
        raise HTTPException(status_code=403, detail="Access denied: no permission for this evidence file")


@app.get("/api/evidence/view")
async def view_evidence_by_token(token: str = Query(...)):
    """Serve an evidence file via a short-lived signed token (no auth header needed)."""
    payload = _verify_evidence_token(token)
    filename = payload.get("filename")
    if not filename:
        raise HTTPException(status_code=400, detail="Token missing filename")
    safe_name = Path(filename).name
    file_path = (_EVIDENCE_DIR / safe_name).resolve()
    if _EVIDENCE_DIR.resolve() not in file_path.parents and file_path != _EVIDENCE_DIR.resolve():
        if file_path.parent.resolve() != _EVIDENCE_DIR.resolve():
            raise HTTPException(status_code=403, detail="Access denied")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Evidence file not found")
    # Also verify the officer still has access (optional but good for revocation)
    # For expiring links we skip the ownership check and rely on token expiry and signature;
    # the token was already verified to be issued to someone with access at issuance time.
    from fastapi.responses import FileResponse
    return FileResponse(str(file_path), media_type="image/png", headers={"Cache-Control": "no-store, max-age=0"})


@app.get("/api/evidence/token/{filename}")
async def get_evidence_token(filename: str, request: Request, expires_in: int = Query(300, ge=30, le=3600)):
    """Generate a short-lived signed URL token for an evidence file."""
    officer = await _auth(request)
    await _check_evidence_access(filename, officer)
    token = _evidence_token_for(Path(filename).name, int(officer["sub"]), expires_in)
    return {
        "filename": Path(filename).name,
        "token": token,
        "expires_in": expires_in,
        "url": f"/api/evidence/view?token={token}",
    }


@app.get("/api/evidence/{filename}")
async def get_evidence_file(filename: str, request: Request):
    """Serve an evidence file — requires authentication and case ownership."""
    officer = await _auth(request)
    await _check_evidence_access(filename, officer)
    safe_name = Path(filename).name
    file_path = (_EVIDENCE_DIR / safe_name).resolve()
    if _EVIDENCE_DIR.resolve() not in file_path.parents and file_path != _EVIDENCE_DIR.resolve():
        if file_path.parent.resolve() != _EVIDENCE_DIR.resolve():
            raise HTTPException(status_code=403, detail="Access denied: path traversal")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Evidence file not found on disk")
    from fastapi.responses import FileResponse
    return FileResponse(str(file_path), media_type="image/png", headers={"Cache-Control": "no-store"})


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

@app.get("/evidence/{path:path}")
async def block_public_evidence(path: str):
    """Block the old public /evidence URL — evidence is now via authenticated /api/evidence."""
    raise HTTPException(status_code=404, detail="Evidence files are now served via authenticated /api/evidence endpoints — please use the case report view")


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

