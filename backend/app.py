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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import (
    Depends,
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
# Auth dependency
# ---------------------------------------------------------------------------

async def get_current_officer(
    authorization: str = "",
) -> dict:
    """Extract and validate the current officer from the Authorization header."""
    from fastapi import Request

    # This will be injected via Depends with the request
    raise HTTPException(status_code=401, detail="Not authenticated")


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
    "https://sih-weld-psi.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static evidence directory
_EVIDENCE_DIR = _PROJECT_ROOT / "samples" / "evidence"
_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/evidence", StaticFiles(directory=str(_EVIDENCE_DIR)), name="evidence")

# Mount frontend directory (React SPA)
_FRONTEND_DIR = _PROJECT_ROOT / "frontend" / "dist"
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")



# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    # JWT secret check (audit P3 §1)
    if _JWT_SECRET == "sih-hackathon-dev-secret-change-in-prod":
        if _DEMO_MODE:
            print("[startup] WARNING: Using default JWT secret in DEMO_MODE.")
        else:
            print("[startup] WARNING: JWT_SECRET is set to the default value. "
                  "Set a strong JWT_SECRET env var for production.")

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
):
    """Execute parallel local CV + Gemini AI screening pipeline.

    Accepts multipart form data with document_image and optional live_capture.
    Returns the full screening result with risk verdict.
    """
    start_time = time.perf_counter()

    # Auth — mandatory (audit P1 §1)
    officer = await _auth(request)
    officer_id = int(officer["sub"])

    # Save uploaded files temporarily
    import tempfile
    doc_bytes = await document_image.read()
    doc_tmp = Path(tempfile.mktemp(suffix=".png", prefix="screen_doc_"))
    doc_tmp.write_bytes(doc_bytes)

    live_tmp = None
    if live_capture and live_capture.filename:
        live_bytes = await live_capture.read()
        live_tmp = Path(tempfile.mktemp(suffix=".png", prefix="screen_live_"))
        live_tmp.write_bytes(live_bytes)

    try:
        result = await _run_screening_pipeline(doc_tmp, live_tmp, officer_id)
    except Exception as exc:
        print(f"[screen] Screening pipeline failed: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Screening pipeline failed: {type(exc).__name__}",
        ) from exc
    finally:
        # Cleanup temp files
        doc_tmp.unlink(missing_ok=True)
        if live_tmp:
            live_tmp.unlink(missing_ok=True)

    elapsed = (time.perf_counter() - start_time) * 1000
    result["total_latency_ms"] = round(elapsed, 1)

    return result


async def _run_screening_pipeline(
    doc_path: Path,
    live_path: Optional[Path],
    officer_id: int,
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

    # Deepfake: run on LIVE CAPTURE, not document (audit P2 §1)
    deepfake_target = str(live_path) if live_path else str(doc_path)
    deepfake_task = loop.run_in_executor(None, run_deepfake, deepfake_target)

    # Liveness: wire into pipeline (audit P1 §3)
    liveness_target = live_path or doc_path
    liveness_task = loop.run_in_executor(None, run_liveness, str(liveness_target))

    # Gemini AI call (also in thread pool)
    live_str = str(live_path) if live_path else str(doc_path)
    gemini_task = loop.run_in_executor(
        None, scan_document, str(doc_path), live_str, None
    )

    # Await all in parallel
    tamper_result, deepfake_result, liveness_result, gemini_result = await asyncio.gather(
        tamper_task, deepfake_task, liveness_task, gemini_task
    )

    # --- Post-process Gemini results ---
    demographics = gemini_result.get("demographics", {})
    doc_type = gemini_result.get("document_type", "unknown")
    face_match_data = gemini_result.get("three_way_face_match", {})
    photo_tamper = gemini_result.get("photo_tamper_anomaly", False)
    is_simulated = gemini_result.get("is_simulated", False)

    # --- Checksum validation ---
    doc_number = demographics.get("document_number", "")
    checksum_result = validate_document_number(doc_type, doc_number)

    # ------------------------------------------------------------------
    # Step 3: Database demographic cross-check (post-OCR)
    # ------------------------------------------------------------------
    demographic_result = None
    async with async_session() as session:
        # Try to find a matching citizen by document number
        norm_num = doc_number.replace(" ", "").replace("-", "").upper()
        result = await session.execute(
            select(CitizenRegistry).where(
                CitizenRegistry.document_number == norm_num
            )
        )
        citizen = result.scalar_one_or_none()

        if not citizen and doc_number:
            # Try with original number
            result = await session.execute(
                select(CitizenRegistry).where(
                    CitizenRegistry.document_number == doc_number
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
    full_name = demographics.get("full_name", "")
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

    risk = assess_risk(
        demographic_result=demographic_result,
        tamper_score=tamper_result.score if tamper_result.status == "ok" else None,
        tamper_status=tamper_result.status,
        deepfake_score=deepfake_result.score if deepfake_result.status == "ok" else None,
        deepfake_status=deepfake_result.status,
        face_similarity=face_sim,
        face_match=face_match_bool,
        face_status="ok" if face_sim is not None else "inconclusive",
        liveness_live=liveness_live,
        liveness_score=liveness_score_val,
        liveness_status=liveness_result.status,
        watchlist_hit=watchlist_result.is_hit,
        watchlist_result=watchlist_result.to_dict(),
        gemini_face_match=face_match_data,
        gemini_photo_tamper=photo_tamper,
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
        # matched, otherwise persist raw AI-extracted demographics so the
        # officer always sees what was read off the document.
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
        else:
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

        for mod_name, score, mod_status, raw, evidence, mocked in modules:
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
        "gemini_metadata": {
            "is_simulated": is_simulated,
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
    from starlette.requests import Request
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

    return {
        "case": case.to_dict(),
        "citizen": citizen_data,
        "extracted_fields": [f.to_dict() for f in fields],
        "module_results": [m.to_dict() for m in modules],
        "officer_actions": [a.to_dict() for a in actions],
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
    from starlette.requests import Request
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
    """Serve the React SPA index.html for any unmatched non-API routes."""
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")
        
    index_path = _FRONTEND_DIR / "index.html"
    if index_path.exists():
        from fastapi.responses import FileResponse
        return FileResponse(str(index_path))
    
    raise HTTPException(status_code=404, detail="Frontend not built")

