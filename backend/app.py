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
from backend.auth_security import (
    DUMMY_HASH,
    app_env,
    client_ip,
    generate_totp_secret,
    is_production,
    match_window,
    otpauth_uri,
    rate_limit_from_env,
    secret_error,
    validate_new_password,
    verify_totp,
)
from backend.models import (
    AuditLog,
    CitizenRegistry,
    ExtractedField,
    IdempotencyRecord,
    IrisTemplate,
    ModuleResultDB,
    Officer,
    OfficerAction,
    RegistryEnrollment,
    ScreeningCase,
)

# ---------------------------------------------------------------------------
# JWT utilities (lightweight, no external deps beyond stdlib + pyjwt)
# ---------------------------------------------------------------------------

_JWT_SECRET = os.environ.get("JWT_SECRET", "sih-hackathon-dev-secret-change-in-prod")
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", "8"))
_DEMO_MODE = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")

# Brute-force throttles (env-tunable; in-memory per process — see docs).
_LOGIN_LIMITER = rate_limit_from_env("LOGIN_RATE_LIMIT", 5, 300)
_MFA_LIMITER = rate_limit_from_env("MFA_RATE_LIMIT", 5, 300)
_MFA_TOKEN_MINUTES = int(os.environ.get("MFA_TOKEN_MINUTES", "5"))


def _utcnow_naive() -> datetime:
    """Naive UTC timestamp for DATABASE columns.

    Postgres asyncpg rejects timezone-aware datetimes for TIMESTAMP WITHOUT
    TIME ZONE (500s the request), while SQLite silently accepts them — so
    only production explodes. All app-written DateTime columns must use this
    (server_default columns are already naive). Never use
    datetime.now(timezone.utc) for a model attribute.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)

try:
    import jwt as pyjwt
    _HAS_PYJWT = True
except ImportError:
    _HAS_PYJWT = False


def _create_token(officer_id: int, username: str, role: str, unit: str = "BORDER_UNIT_1",
                  purpose: str = "session", expiry_minutes: Optional[int] = None) -> str:
    """Create a JWT token for an authenticated officer.

    purpose="session" (default, honoured by _auth) or "mfa" (short-lived
    step-up token for the second factor — rejected by _auth everywhere).
    """
    import uuid as _uuid
    jti = _uuid.uuid4().hex
    minutes = expiry_minutes if expiry_minutes is not None else _JWT_EXPIRY_HOURS * 60
    if _HAS_PYJWT:
        payload = {
            "sub": str(officer_id),
            "username": username,
            "role": role,
            "unit": unit,
            "jti": jti,
            "purpose": purpose,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes),
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
            "purpose": purpose,
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
            "physical_forgery": {"method": "layout+mrz_font+photo_frame+printscan_moire+qr+hologram_inventory"},
            "deepfake": {"method": "fft_frequency_artifact_heuristic"},
            "gemini": {"model": os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")},
            "iris": {"name": "RGBProvider", "version": "1.0-rgb-prototype", "note": "RGB prototype, not NIR production-grade"},
            "risk_engine": {"version": "1.0", "rules": "Green<0.35<Yellow<0.65<Red"},
        },
        "thresholds": {
            "face_match": _face_thr,
            "tamper_high": 0.7,
            "tamper_moderate": 0.4,
            "physical_high": 0.7,
            "physical_moderate": 0.4,
            "deepfake_high": 0.7,
            "liveness": 0.45,
            "iris_match": 0.32,
            "iris_low_conf_low": 0.28,
            "iris_low_conf_high": 0.36,
            "iris_calibration": "uncalibrated-prototype",
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

# CORS — extend via CORS_ORIGINS (comma-separated) on the deploy host, e.g.
# CORS_ORIGINS="https://app.example.com,https://api.example.com"
_CORS_DEFAULTS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://[::1]:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://[::1]:8000",
    "https://sih-weld-psi.vercel.app",
    "https://netraksha.xyz",
    "https://www.netraksha.xyz",
]
_CORS_EXTRA = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_DEFAULTS + [o for o in _CORS_EXTRA if o not in _CORS_DEFAULTS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    """Last-resort JSON 500 that still passes through CORSMiddleware.

    Without this, an unhandled crash returns Starlette's bare 500 with NO
    CORS headers, and cross-origin browsers misreport it as a CORS error —
    hiding the real traceback from both the UI and the Render logs reader.
    HTTPException subclasses keep their own status/detail (handled above us).
    """
    from fastapi.responses import JSONResponse

    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code,
                            content={"detail": exc.detail})
    print(f"[unhandled] {request.method} {request.url.path}: "
          f"{type(exc).__name__}: {exc}")
    return JSONResponse(status_code=500, content={
        "detail": "Internal server error. The incident has been logged — "
                  "retry once, then contact support with the time.",
    })

# Evidence directory (no longer publicly mounted — served via authenticated endpoints below)
# Respects SCREEN_EVIDENCE_DIR (blank = unset) so deploys can point at a
# persistent volume; mirrors pipeline/common.py EVIDENCE_DIR resolution.
_EVIDENCE_ENV = os.environ.get("SCREEN_EVIDENCE_DIR", "").strip()
_EVIDENCE_DIR = Path(_EVIDENCE_ENV) if _EVIDENCE_ENV else _PROJECT_ROOT / "samples" / "evidence"
_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

# Frontend build directory (served statically via the SPA fallback route)
_FRONTEND_DIR = _PROJECT_ROOT / "frontend" / "dist"



# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    # Secrets gate: production FAILS FAST on default/weak secrets instead of
    # serving with forgeable tokens. Development keeps soft warnings.
    _jwt_problem = secret_error(_JWT_SECRET, name="JWT_SECRET")
    if _jwt_problem and is_production():
        raise RuntimeError(f"[startup] {_jwt_problem}")
    elif _jwt_problem:
        print(f"[startup] WARNING: {_jwt_problem}")
        # Previously this raised outside DEMO_MODE and blocked `uvicorn --reload`
        # with the stock .env; keep it as a soft warning so local Supabase/SQLite
        # dev works out-of-the-box.

    # NOTE: no standalone init_db() here — seed_all() opens with init_db()
    # (tables + drift repair). A separate call doubles the slow
    # information_schema/ALTER pass and trips Render's "No open ports
    # detected" warning on cold starts.
    _reg_problem = secret_error(_REGISTRY_IMPORT_SECRET, name="REGISTRY_IMPORT_SECRET")
    if _reg_problem and is_production():
        raise RuntimeError(f"[startup] {_reg_problem} Generate one (python -c "
                           f"\"import secrets; print(secrets.token_hex(32))\") and share it "
                           f"with the issuing authority over a secure channel.")
    elif _REGISTRY_IMPORT_SECRET_FALLBACK:
        print("[startup] WARNING: REGISTRY_IMPORT_SECRET not set — authority imports are signed with JWT_SECRET. Set a dedicated REGISTRY_IMPORT_SECRET in .env for production.")
    # Auto-seed if database is empty
    try:
        from backend.seed import seed_all
        result = await seed_all()
        print(f"[startup] Database seeded: {result}")
    except Exception as e:
        # In production a seed refusal (missing bootstrap admin, weak
        # password) must fail the deploy loudly — never start admin-less.
        if is_production():
            raise
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

    # Registry photo backend: log which photo_uri forms will resolve (no secrets).
    try:
        _photo_backend = _registry_photo_backend_status()
        print(f"[startup] Registry photos: mode={_photo_backend['mode']} bucket={_photo_backend['bucket']} "
              f"configured={_photo_backend['configured']} private_reads={_photo_backend['private_reads']}")
        if not _photo_backend["configured"]:
            print("[startup] WARNING: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY not set — "
                  "Storage refs like 'img/<object>' will NOT resolve; only local paths + public http(s) URLs work.")
    except Exception as e:
        print(f"[startup] Registry photo backend check warning: {e}")

    # Background prewarm of the local InsightFace engine (non-blocking):
    # a first-use ~300MB buffalo_l download happens here — loudly — instead
    # of timing out somebody's first screening with silent N/A face legs.
    # Allow explicit opt-out of the heavyweight InsightFace engine
    # (e.g. Render free tier: 512MB RAM, buffalo_l needs ~300MB).
    if os.environ.get("DISABLE_LOCAL_FACE_ENGINE", "").lower() in ("1", "true", "yes"):
        print("[startup] Local face engine DISABLED (DISABLE_LOCAL_FACE_ENGINE=true). "
              "Face match will use Gemini fallback; registry legs will be N/A.")
    else:
        try:
            async def _bg_face_prewarm():
                try:
                    from pipeline.face_match import prewarm_local_engine
                    ok = await asyncio.get_event_loop().run_in_executor(None, prewarm_local_engine)
                    print(f"[startup] Local face engine prewarm: "
                          f"{'READY' if ok else 'UNAVAILABLE — registry face legs will be N/A until models are provisioned'}")
                except Exception as e:
                    print(f"[startup] Face prewarm warning: {type(e).__name__}: {e}")
            asyncio.create_task(_bg_face_prewarm())
        except Exception as e:
            print(f"[startup] Face prewarm scheduling warning: {e}")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str = ""
    officer_id: int = 0
    username: str = ""
    role: str = ""
    # Step-up / rotation signals (empty token when one of these is set).
    mfa_required: bool = False
    mfa_token: str = ""
    must_change_password: bool = False
    mfa_setup_required: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class MfaChallengeRequest(BaseModel):
    mfa_token: str
    code: str


class MfaVerifyRequest(BaseModel):
    code: str


class MfaDisableRequest(BaseModel):
    password: str
    code: str


class OverrideRequest(BaseModel):
    action: str  # clear | deny | escalate
    reason: str
    version: Optional[int] = None  # for optimistic locking (client's expected version)


# ---------------------------------------------------------------------------
# Auth helper — extract officer from Bearer token
# ---------------------------------------------------------------------------

async def _auth(request, allow_stale_password: bool = False,
                allow_mfa_setup: bool = False) -> dict:
    """Extract officer info from Authorization header and enrich with fresh DB state.

    Enforcement (rotation + supervisor MFA) is ON by default: accounts flagged
    must_change_password get 403 PASSWORD_CHANGE_REQUIRED, and supervisors who
    have not enrolled TOTP get 403 MFA_SETUP_REQUIRED. Pass the allow_* flags
    only for the endpoints that clear those states (change-password, MFA
    setup/verify, logout). MFA step-up tokens (purpose="mfa") are rejected
    everywhere — they are only valid at POST /api/auth/mfa/challenge.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = auth[7:]
    payload = _decode_token(token)
    if payload.get("purpose", "session") != "session":
        raise HTTPException(status_code=401, detail="Invalid token purpose for this endpoint")
    # Enrich with current DB state for unit/role (handles old tokens missing unit)
    must_change = False
    mfa_pending = False
    try:
        async with async_session() as session:
            res = await session.execute(select(Officer).where(Officer.id == int(payload.get("sub", 0))))
            off = res.scalar_one_or_none()
            if off:
                payload["unit"] = getattr(off, "unit", None) or payload.get("unit") or "BORDER_UNIT_1"
                payload["role"] = off.role or payload.get("role", "officer")
                payload["username"] = off.username
                must_change = bool(getattr(off, "must_change_password", False))
                mfa_pending = (
                    payload["role"] == "supervisor"
                    and not bool(getattr(off, "totp_enabled", False))
                )
    except Exception:
        pass
    payload.setdefault("unit", "BORDER_UNIT_1")
    payload.setdefault("role", "officer")
    if must_change and not allow_stale_password:
        raise HTTPException(status_code=403, detail="PASSWORD_CHANGE_REQUIRED: rotate your password before continuing.")
    if mfa_pending and not allow_mfa_setup:
        raise HTTPException(status_code=403, detail="MFA_SETUP_REQUIRED: supervisors must enroll authenticator MFA before continuing.")
    return payload


# ---------------------------------------------------------------------------
# 1. POST /api/auth/login
# ---------------------------------------------------------------------------

@app.post("/auth/login", response_model=LoginResponse, include_in_schema=False)
@app.post("/api/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request):
    """Authenticate officer, generate JWT session.

    Brute-force throttled per client IP and per username (429 when tripped).
    Unknown usernames are dummy-verified so timing reveals nothing. Supervisors
    with TOTP enrolled receive a short-lived mfa_token instead of a session
    and must complete POST /api/auth/mfa/challenge.
    """
    ip = client_ip(request)
    username = (req.username or "").strip()
    ok_ip, retry_ip = _LOGIN_LIMITER.check(f"ip:{ip}")
    ok_user, retry_user = _LOGIN_LIMITER.check(f"user:{username.lower()}")
    if not (ok_ip and ok_user):
        raise HTTPException(
            status_code=429,
            detail=f"Too many login attempts. Retry in {max(retry_ip, retry_user)}s.")

    async with async_session() as session:
        result = await session.execute(
            select(Officer).where(Officer.username == username)
        )
        officer = result.scalar_one_or_none()

    # Timing-equalized verification (unknown users check a dummy hash).
    password_ok = _verify_password(
        req.password, officer.password_hash if officer else DUMMY_HASH)
    if not officer or not password_ok:
        _LOGIN_LIMITER.register_failure(f"ip:{ip}")
        _LOGIN_LIMITER.register_failure(f"user:{username.lower()}")
        async with async_session() as session:
            session.add(AuditLog(
                actor=username or "unknown",
                action="login_failed",
                entity=f"officer:{username or '?'}",
                device_info=f"IP:{ip}",
            ))
            await session.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    _LOGIN_LIMITER.register_success(f"ip:{ip}")
    _LOGIN_LIMITER.register_success(f"user:{username.lower()}")
    must_change = bool(getattr(officer, "must_change_password", False))
    mfa_enabled = bool(getattr(officer, "totp_enabled", False))
    mfa_setup_required = officer.role == "supervisor" and not mfa_enabled
    unit = getattr(officer, "unit", "BORDER_UNIT_1") or "BORDER_UNIT_1"

    if mfa_enabled:
        mfa_token = _create_token(officer.id, officer.username, officer.role, unit,
                                  purpose="mfa", expiry_minutes=_MFA_TOKEN_MINUTES)
        async with async_session() as session:
            session.add(AuditLog(
                actor=officer.username,
                action="login_mfa_challenged",
                entity=f"officer:{officer.id}",
            ))
            await session.commit()
        return LoginResponse(
            mfa_required=True,
            mfa_token=mfa_token,
            officer_id=officer.id,
            username=officer.username,
            role=officer.role,
            must_change_password=must_change,
            mfa_setup_required=mfa_setup_required,
        )

    token = _create_token(officer.id, officer.username, officer.role, unit)

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
        must_change_password=must_change,
        mfa_setup_required=mfa_setup_required,
    )


def _drift_hint(secret, code) -> str:
    """Explain an MFA rejection without weakening it.

    The accept/reject decision always stays at ±1 step; this only inspects a
    wider window to tell a clock problem ("your code is ~N minutes off") from
    a wrong-key problem ("doesn't match at all — re-scan"). Safe to expose:
    the caller already passed password/session auth and attempts are
    rate-limited, and knowing drift is useless without the secret itself.
    """
    try:
        drift = match_window(secret, code) if secret else None
    except Exception:
        drift = None
    if drift is None:
        return ("Invalid authenticator code. If you re-started enrollment, make sure "
                "you're reading the newest Netraksha entry in your app — old entries stop working.")
    minutes = max(1, round(abs(drift) * 30 / 60))
    return (f"That code is ~{minutes} minute(s) off current time — your phone clock disagrees "
            f"with the server. Turn on automatic date & time, wait for a fresh code, and retry.")


@app.post("/api/auth/mfa/challenge", response_model=LoginResponse)
async def mfa_challenge(req: MfaChallengeRequest, request: Request):
    """Complete supervisor MFA login with a TOTP code. Issues the session."""
    try:
        payload = _decode_token(req.mfa_token)
    except HTTPException:
        raise HTTPException(status_code=401, detail="MFA token expired — sign in again.")
    if payload.get("purpose") != "mfa":
        raise HTTPException(status_code=401, detail="Invalid MFA token.")
    officer_id = int(payload.get("sub", 0) or 0)
    ok, retry = _MFA_LIMITER.check(f"mfa:{officer_id}")
    if not ok:
        raise HTTPException(
            status_code=429, detail=f"Too many code attempts. Retry in {retry}s.")
    async with async_session() as session:
        result = await session.execute(select(Officer).where(Officer.id == officer_id))
        officer = result.scalar_one_or_none()
    secret = getattr(officer, "totp_secret", None) if officer else None
    enabled = bool(getattr(officer, "totp_enabled", False)) if officer else False
    if not officer or not enabled or not secret or not verify_totp(secret, req.code):
        _MFA_LIMITER.register_failure(f"mfa:{officer_id}")
        raise HTTPException(status_code=401, detail=_drift_hint(secret, req.code))
    _MFA_LIMITER.register_success(f"mfa:{officer_id}")
    unit = getattr(officer, "unit", "BORDER_UNIT_1") or "BORDER_UNIT_1"
    token = _create_token(officer.id, officer.username, officer.role, unit)
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
        must_change_password=bool(getattr(officer, "must_change_password", False)),
        mfa_setup_required=False,
    )


@app.post("/api/auth/change-password")
async def change_password(req: ChangePasswordRequest, request: Request):
    """Rotate the caller's password (also clears the must-change flag)."""
    officer = await _auth(request, allow_stale_password=True, allow_mfa_setup=True)
    officer_id = int(officer["sub"])
    async with async_session() as session:
        result = await session.execute(select(Officer).where(Officer.id == officer_id))
        off = result.scalar_one_or_none()
        if not off:
            raise HTTPException(status_code=401, detail="Invalid token")
        if not _verify_password(req.current_password, off.password_hash):
            raise HTTPException(status_code=401, detail="Current password is incorrect.")
        try:
            validate_new_password(req.new_password)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if _verify_password(req.new_password, off.password_hash):
            raise HTTPException(status_code=400, detail="New password must differ from the current one.")
        from passlib.context import CryptContext
        off.password_hash = CryptContext(schemes=["bcrypt"], deprecated="auto").hash(req.new_password)
        off.must_change_password = False
        try:
            off.password_changed_at = _utcnow_naive()
        except Exception:
            pass
        session.add(AuditLog(
            actor=off.username,
            action="password_changed",
            entity=f"officer:{off.id}",
            officer_id=off.id,
        ))
        await session.commit()
    return {"status": "ok", "message": "Password changed."}


@app.post("/api/auth/mfa/setup")
async def mfa_setup(request: Request):
    """Begin supervisor TOTP enrollment.

    Returns a scannable QR (preferred — no typing), plus the manual key +
    otpauth URI fallback. Confirm with POST /api/auth/mfa/verify.
    """
    officer = await _auth(request, allow_stale_password=True, allow_mfa_setup=True)
    _require_role(officer, "supervisor")
    officer_id = int(officer["sub"])
    async with async_session() as session:
        result = await session.execute(select(Officer).where(Officer.id == officer_id))
        off = result.scalar_one_or_none()
        if not off:
            raise HTTPException(status_code=401, detail="Invalid token")
        if bool(getattr(off, "totp_enabled", False)):
            raise HTTPException(status_code=400, detail="MFA is already enabled. Disable it first to re-enroll.")
        secret = generate_totp_secret()
        off.totp_secret = secret
        off.totp_enabled = False
        session.add(AuditLog(
            actor=off.username,
            action="mfa_enrollment_started",
            entity=f"officer:{off.id}",
            officer_id=off.id,
        ))
        await session.commit()
    uri = otpauth_uri(secret, off.username)
    qr_data_uri = ""
    try:
        import base64 as _b64
        import io as _io
        import qrcode as _qr
        _buf = _io.BytesIO()
        _qr.make(uri).save(_buf, format="PNG")
        qr_data_uri = "data:image/png;base64," + _b64.b64encode(_buf.getvalue()).decode()
    except Exception:
        qr_data_uri = ""  # manual key fallback below always works
    return {
        "status": "ok",
        "manual_key": secret,
        "otpauth_uri": uri,
        "qr_data_uri": qr_data_uri,
        "server_time_utc": _utcnow_naive().isoformat() + "Z",
        "message": "Scan the QR with your authenticator app (or enter the manual key), then confirm with POST /api/auth/mfa/verify.",
    }


@app.post("/api/auth/mfa/verify")
async def mfa_verify(req: MfaVerifyRequest, request: Request):
    """Confirm TOTP enrollment with a code from the authenticator app."""
    officer = await _auth(request, allow_stale_password=True, allow_mfa_setup=True)
    _require_role(officer, "supervisor")
    officer_id = int(officer["sub"])
    ok, retry = _MFA_LIMITER.check(f"mfa:{officer_id}")
    if not ok:
        raise HTTPException(status_code=429, detail=f"Too many code attempts. Retry in {retry}s.")
    async with async_session() as session:
        result = await session.execute(select(Officer).where(Officer.id == officer_id))
        off = result.scalar_one_or_none()
        if not off or not getattr(off, "totp_secret", None):
            raise HTTPException(status_code=400, detail="No MFA enrollment in progress. Call POST /api/auth/mfa/setup first.")
        if not verify_totp(off.totp_secret, req.code):
            _MFA_LIMITER.register_failure(f"mfa:{officer_id}")
            raise HTTPException(status_code=401, detail=_drift_hint(off.totp_secret, req.code))
        _MFA_LIMITER.register_success(f"mfa:{officer_id}")
        off.totp_enabled = True
        session.add(AuditLog(
            actor=off.username,
            action="mfa_enabled",
            entity=f"officer:{off.id}",
            officer_id=off.id,
        ))
        await session.commit()
    return {"status": "ok", "message": "MFA enabled for your supervisor account."}


@app.post("/api/auth/mfa/disable")
async def mfa_disable(req: MfaDisableRequest, request: Request):
    """Disable your own supervisor MFA (password + current code required)."""
    officer = await _auth(request, allow_stale_password=True, allow_mfa_setup=True)
    _require_role(officer, "supervisor")
    officer_id = int(officer["sub"])
    async with async_session() as session:
        result = await session.execute(select(Officer).where(Officer.id == officer_id))
        off = result.scalar_one_or_none()
        if not off:
            raise HTTPException(status_code=401, detail="Invalid token")
        if not _verify_password(req.password, off.password_hash):
            raise HTTPException(status_code=401, detail="Password is incorrect.")
        if bool(getattr(off, "totp_enabled", False)) and not verify_totp(
                getattr(off, "totp_secret", "") or "", req.code):
            raise HTTPException(status_code=401, detail="Invalid authenticator code.")
        off.totp_secret = None
        off.totp_enabled = False
        session.add(AuditLog(
            actor=off.username,
            action="mfa_disabled",
            entity=f"officer:{off.id}",
            officer_id=off.id,
        ))
        await session.commit()
    return {"status": "ok", "message": "MFA disabled. Re-enroll before continuing operational work."}


# ---------------------------------------------------------------------------
# 2. POST /api/auth/logout
# ---------------------------------------------------------------------------

@app.post("/auth/logout", include_in_schema=False)
@app.post("/api/auth/logout")
async def logout(request: Request):
    """Terminate session (audit log only — JWT is stateless)."""
    try:
        officer = await _auth(request, allow_stale_password=True, allow_mfa_setup=True)
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
#   Idempotency: requires `Idempotency-Key` header (or `idempotency_key`
#   form field fallback). Deduplicates by (officer, session, input hash, key).
# ---------------------------------------------------------------------------

import re as _re

_IDEMPOTENCY_KEY_RE = _re.compile(r"^[A-Za-z0-9\-_:.]{8,128}$")
# Second-layer dedup window: same officer + session + input hash with a
# *different* key still returns the original case (double-click guard).
# Short window so a legitimate re-screen later creates a fresh case.
_IDEMPOTENCY_HASH_WINDOW_MINUTES = 10


def _extract_idempotency_key(request: Request, form_fallback: Optional[str] = None) -> str:
    """Require a client-supplied idempotency key.

    Accepts `Idempotency-Key` (standard) or `X-Idempotency-Key`, falling back
    to the multipart `idempotency_key` form field for non-JS clients.
    Raises 422 when missing or malformed.
    """
    key = (
        request.headers.get("Idempotency-Key")
        or request.headers.get("X-Idempotency-Key")
        or (form_fallback or "")
    )
    key = (key or "").strip()
    if not key:
        raise HTTPException(
            status_code=422,
            detail="Missing Idempotency-Key: include a UUID v4 in the "
                   "`Idempotency-Key` header (reuse the same key on retry).",
        )
    if not _IDEMPOTENCY_KEY_RE.match(key):
        raise HTTPException(
            status_code=422,
            detail="Invalid Idempotency-Key: must be 8-128 chars of "
                   "letters, digits, hyphen, underscore, colon or dot "
                   "(UUID v4 recommended).",
        )
    return key


def _compute_input_hash(file_hashes: dict) -> str:
    """Stable SHA-256 over the sorted per-file hashes (officer/session-independent)."""
    try:
        canonical = json.dumps(file_hashes or {}, sort_keys=True).encode()
    except Exception:
        canonical = str(sorted((file_hashes or {}).items())).encode()
    return hashlib.sha256(canonical).hexdigest()


async def _load_case_result_payload(case_id: int) -> Optional[dict]:
    """Rebuild the screening response body for an already-completed case.

    Used for idempotent replays when no snapshot was stored (e.g. legacy
    rows). Returns None if the case no longer exists.
    """
    async with async_session() as session:
        res = await session.execute(select(ScreeningCase).where(ScreeningCase.id == case_id))
        case = res.scalar_one_or_none()
        if not case:
            return None
        fields_res = await session.execute(
            select(ExtractedField).where(ExtractedField.case_id == case_id)
        )
        mods_res = await session.execute(
            select(ModuleResultDB).where(ModuleResultDB.case_id == case_id)
        )
        mod_rows = mods_res.scalars().all()
        modules = {m.module_name: m.to_dict() for m in mod_rows}
        gem_raw = (modules.get("gemini_ai") or {}).get("raw_output") or {}
        face = (gem_raw.get("three_way_face_match") if isinstance(gem_raw, dict) else None) or {}
        return {
            "case_id": case.id,
            "document_type": case.document_type,
            "risk_assessment": {
                "verdict": case.verdict,
                "risk_score": case.risk_score,
            },
            "module_results": list(modules.values()),
            "extracted_fields": [f.to_dict() for f in fields_res.scalars().all()],
            "face_verification": face,
            "is_demo": bool((modules.get("gemini_ai") or {}).get("is_mocked")),
        }


@app.post("/screen", include_in_schema=False)
@app.post("/api/screen")
async def screen_document(
    request: Request,
    document_image: UploadFile = File(...),
    live_capture: UploadFile = File(None),
    live_frames: List[UploadFile] = File(None),
    iris_image: UploadFile = File(None),
    iris_eye: Optional[str] = Form(None),
    idempotency_key: Optional[str] = Form(None),
):
    """Execute parallel local CV + Gemini AI screening pipeline.

    Accepts multipart form data with document_image, an optional single
    live_capture, and/or an optional live_frames burst (multiple frames) so the
    liveness module receives enough frames for blink/EAR detection.
    Returns the full screening result with risk verdict.

    Idempotency (duplicate-retry guard): the caller MUST send an
    `Idempotency-Key` header. Retries with the same key + same officer +
    same session + same input bytes return the original case instead of
    creating a duplicate.
    """
    start_time = time.perf_counter()

    # Auth — mandatory (audit P1 §1)
    officer = await _auth(request)
    officer_id = int(officer["sub"])
    session_id = officer.get("jti") or officer.get("session_id") or ""
    # Idempotency key is REQUIRED — clients must reuse it on retry.
    key = _extract_idempotency_key(request, idempotency_key)
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
    # Hash input files for audit trail + idempotency input hash
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

    # Iris source — unified person capture: prefer explicit iris_image for
    # backward compat (e.g. enrollment retest), otherwise derive the eye crop
    # server-side from the SAME live burst that feeds face/liveness. No second
    # camera is opened; iris_eye="auto" picks the best-quality eye.
    iris_tmp = None
    iris_eye_val = (iris_eye or "auto").strip().lower()
    iris_derived = False
    if iris_image and iris_image.filename:
        iris_bytes = await iris_image.read()
        file_hashes["iris"] = hashlib.sha256(iris_bytes).hexdigest()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png", prefix="screen_iris_") as tmp:
            tmp.write(iris_bytes)
            iris_tmp = Path(tmp.name)
    elif burst:
        # Derive eye crop from the best (middle) burst frame of the same capture.
        try:
            import cv2 as _cv2
            from backend.biometric.iris.detector import detect_eyes as _detect_eyes
            from backend.biometric.iris.quality import assess_iris_quality as _iris_quality
            _candidates = [burst[len(burst) // 2]] + burst  # middle frame first
            _best_crop = None
            _best_eye = "left"
            _best_score = -1.0
            for _cand in _candidates:
                try:
                    _img = _cv2.imread(str(_cand))
                    if _img is None:
                        continue
                    _det = _detect_eyes(_img)
                    if _det.get("status") != "ok":
                        continue
                    for _ename in (["left", "right"] if iris_eye_val in ("auto", "") else [iris_eye_val if iris_eye_val in ("left", "right") else "left"]):
                        _eye = _det.get(f"{_ename}_eye", _det.get(_ename))
                        if not _eye or _eye.get("crop") is None:
                            continue
                        _q = _iris_quality(_eye["crop"])
                        _score = float(_q.get("quality", 0.0)) if isinstance(_q, dict) else 0.0
                        if _score > _best_score:
                            _best_score = _score
                            _best_crop = _eye["crop"]
                            _best_eye = _ename
                    if _best_crop is not None and _best_score >= 0.5:
                        break
                except Exception:
                    continue
            if _best_crop is not None:
                _ok, _buf = _cv2.imencode(".png", _best_crop)
                if _ok:
                    _eye_bytes = bytes(_buf)
                    file_hashes["iris"] = hashlib.sha256(_eye_bytes).hexdigest()
                    file_hashes["iris_derived_from"] = hashlib.sha256(
                        f"burst:{len(burst)}:{_best_eye}".encode()
                    ).hexdigest()
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".png", prefix="screen_iris_unified_") as tmp:
                        tmp.write(_eye_bytes)
                        iris_tmp = Path(tmp.name)
                    iris_eye_val = _best_eye
                    iris_derived = True
        except Exception as _e:
            print(f"[iris] unified eye-crop derivation failed: {type(_e).__name__}: {_e}")

    input_hash = _compute_input_hash(file_hashes)

    # --- Idempotency check #1: exact key replay -------------------------
    # Same (officer, key) seen before → return original, never a new case.
    # Same key with a different session/input → 422 (client bug).
    async with async_session() as _idem_session:
        _existing = await _idem_session.execute(
            select(IdempotencyRecord).where(
                (IdempotencyRecord.officer_id == officer_id)
                & (IdempotencyRecord.idempotency_key == key)
            )
        )
        _row = _existing.scalar_one_or_none()
        if _row is not None:
            if (_row.session_id or "") != (session_id or "") or _row.input_hash != input_hash:
                for p in [doc_tmp, live_tmp, *live_frame_tmps, iris_tmp]:
                    try:
                        if p:
                            p.unlink(missing_ok=True)
                    except Exception:
                        pass
                raise HTTPException(
                    status_code=422,
                    detail="Idempotency-Key was already used with different "
                           "session or input bytes. Generate a fresh key for a new screening.",
                )
            if _row.case_id is None:
                # Stale in-progress claims (crash/killed worker) must not block
                # the key forever — expire after 5 min and allow a fresh attempt.
                try:
                    _created_at = _row.created_at
                    if _created_at is not None and _created_at.tzinfo is None:
                        _created_at = _created_at.replace(tzinfo=timezone.utc)
                    _age = (datetime.now(timezone.utc) - _created_at).total_seconds() if _created_at else 0
                except Exception:
                    _age = 0
                if _age > 300:
                    try:
                        await _idem_session.delete(_row)
                        await _idem_session.commit()
                    except Exception:
                        await _idem_session.rollback()
                    # Fall through to claim + process below.
                else:
                    for p in [doc_tmp, live_tmp, *live_frame_tmps, iris_tmp]:
                        try:
                            if p:
                                p.unlink(missing_ok=True)
                        except Exception:
                            pass
                    raise HTTPException(
                        status_code=409,
                        detail="Screening with this Idempotency-Key is already in progress. "
                               "Wait for the original request to finish instead of retrying.",
                    )
                _row = None  # stale claim purged — treat as first attempt below
            if _row is not None and _row.case_id is not None:
                # Completed replay — return the stored snapshot verbatim.
                try:
                    snapshot = json.loads(_row.response_snapshot) if _row.response_snapshot else None
                except Exception:
                    snapshot = None
                if snapshot is None:
                    snapshot = await _load_case_result_payload(_row.case_id) or {"case_id": _row.case_id}
                if isinstance(snapshot, dict):
                    snapshot = {**snapshot, "deduplicated": True, "idempotency_key": key}
                for p in [doc_tmp, live_tmp, *live_frame_tmps, iris_tmp]:
                    try:
                        if p:
                            p.unlink(missing_ok=True)
                    except Exception:
                        pass
                return snapshot
            # _row is None here (no prior key, or stale claim just purged) —
            # fall through to check #2 + claim below.

        # --- Idempotency check #2: same officer + session + input bytes ----
        # Catches double-clicks / parallel retries that minted a fresh key.
        try:
            _cutoff = datetime.now(timezone.utc) - timedelta(minutes=_IDEMPOTENCY_HASH_WINDOW_MINUTES)
        except Exception:
            _cutoff = None
        _dup_q = (
            select(IdempotencyRecord)
            .where(
                (IdempotencyRecord.officer_id == officer_id)
                & (IdempotencyRecord.session_id == (session_id or ""))
                & (IdempotencyRecord.input_hash == input_hash)
                & (IdempotencyRecord.case_id.is_not(None))
            )
            .order_by(IdempotencyRecord.id.desc())
            .limit(5)
        )
        _dup_res = await _idem_session.execute(_dup_q)
        for _cand in _dup_res.scalars().all():
            try:
                _created = _cand.created_at
                if _created is not None and _created.tzinfo is None:
                    _created = _created.replace(tzinfo=timezone.utc)
                if _cutoff is not None and _created is not None and _created < _cutoff:
                    continue
            except Exception:
                pass
            try:
                snapshot = json.loads(_cand.response_snapshot) if _cand.response_snapshot else None
            except Exception:
                snapshot = None
            if snapshot is None:
                snapshot = await _load_case_result_payload(_cand.case_id) or {"case_id": _cand.case_id}
            if isinstance(snapshot, dict):
                snapshot = {
                    **snapshot,
                    "deduplicated": True,
                    "idempotency_key": key,
                    "duplicate_of_key": _cand.idempotency_key,
                }
            for p in [doc_tmp, live_tmp, *live_frame_tmps, iris_tmp]:
                try:
                    if p:
                        p.unlink(missing_ok=True)
                except Exception:
                    pass
            return snapshot

        # --- Claim the key BEFORE running the pipeline --------------------
        # The UNIQUE(officer_id, idempotency_key) constraint makes concurrent
        # duplicates fail here; the loser returns the winner's case.
        _claim = IdempotencyRecord(
            idempotency_key=key,
            officer_id=officer_id,
            session_id=session_id or "",
            input_hash=input_hash,
            case_id=None,
        )
        _idem_session.add(_claim)
        try:
            await _idem_session.commit()
        except Exception:
            await _idem_session.rollback()
            _race = await _idem_session.execute(
                select(IdempotencyRecord).where(
                    (IdempotencyRecord.officer_id == officer_id)
                    & (IdempotencyRecord.idempotency_key == key)
                )
            )
            _winner = _race.scalar_one_or_none()
            for p in [doc_tmp, live_tmp, *live_frame_tmps, iris_tmp]:
                try:
                    if p:
                        p.unlink(missing_ok=True)
                except Exception:
                    pass
            if _winner is not None and _winner.case_id is not None:
                try:
                    snapshot = json.loads(_winner.response_snapshot) if _winner.response_snapshot else None
                except Exception:
                    snapshot = None
                if snapshot is None:
                    snapshot = await _load_case_result_payload(_winner.case_id) or {"case_id": _winner.case_id}
                if isinstance(snapshot, dict):
                    snapshot = {**snapshot, "deduplicated": True, "idempotency_key": key}
                return snapshot
            raise HTTPException(
                status_code=409,
                detail="Screening with this Idempotency-Key is already in progress. "
                       "Wait for the original request to finish instead of retrying.",
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
            "session_id": session_id,
            "request_id": request_id,
            "device_info": device_info,
            "file_hashes": file_hashes,
        }
        # Include iris if provided (explicit upload or unified-burst-derived eye crop)
        _iris_path = str(iris_tmp) if 'iris_tmp' in locals() and iris_tmp else None
        _iris_eye = iris_eye_val if 'iris_eye_val' in locals() else "left"
        _iris_source = "unified_burst_derived" if (iris_derived if 'iris_derived' in locals() else False) else ("separate_upload" if _iris_path else "none")
        try:
            result = await _run_screening_pipeline(doc_tmp, live_tmp, officer_id, officer_unit, burst, audit_context, iris_path=_iris_path, iris_eye=_iris_eye, iris_source=_iris_source)
        except TypeError:
            # Fallback for pipeline without iris support
            result = await _run_screening_pipeline(doc_tmp, live_tmp, officer_id, officer_unit, burst, audit_context)
    except Exception:
        # Pipeline failed — release the key immediately so a retry with the
        # SAME key can proceed instead of hitting 409 for 5 minutes.
        try:
            async with async_session() as _fail_session:
                _res = await _fail_session.execute(
                    select(IdempotencyRecord).where(
                        (IdempotencyRecord.officer_id == officer_id)
                        & (IdempotencyRecord.idempotency_key == key)
                        & (IdempotencyRecord.case_id.is_(None))
                    )
                )
                _failed = _res.scalar_one_or_none()
                if _failed is not None:
                    await _fail_session.delete(_failed)
                    await _fail_session.commit()
        except Exception:
            pass
        raise
    finally:
        # Cleanup temp files (iris_tmp is derived-or-uploaded eye crop; never persisted raw)
        doc_tmp.unlink(missing_ok=True)
        if live_tmp:
            live_tmp.unlink(missing_ok=True)
        for p in live_frame_tmps:
            p.unlink(missing_ok=True)
        try:
            if 'iris_tmp' in locals() and iris_tmp:
                iris_tmp.unlink(missing_ok=True)
        except Exception:
            pass

    elapsed = (time.perf_counter() - start_time) * 1000
    result["total_latency_ms"] = round(elapsed, 1)
    result["request_id"] = request_id
    result["session_id"] = session_id
    result["idempotency_key"] = key
    result["input_hash"] = input_hash
    result["deduplicated"] = False
    # Also expose request_id as a response header for tracing (if using JSONResponse, set header)
    try:
        from fastapi.responses import JSONResponse
        # If the caller expects a dict, FastAPI will still handle JSONResponse
        # We keep returning dict for simplicity, but also ensure request_id is in the JSON
        pass
    except Exception:
        pass

    # --- Complete the idempotency claim with the new case -----------------
    try:
        async with async_session() as _done_session:
            _res = await _done_session.execute(
                select(IdempotencyRecord).where(
                    (IdempotencyRecord.officer_id == officer_id)
                    & (IdempotencyRecord.idempotency_key == key)
                )
            )
            _rec = _res.scalar_one_or_none()
            if _rec is not None:
                _rec.case_id = result.get("case_id")
                try:
                    _rec.response_snapshot = json.dumps(result, default=str)
                except Exception:
                    _rec.response_snapshot = json.dumps({"case_id": result.get("case_id")})
                await _done_session.commit()
    except Exception as e:
        # Never fail the screening response because the dedup bookkeeping failed.
        print(f"[idempotency] failed to complete claim for key {key[:8]}...: {e}")

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
    # MRZ gives "M"/"F"; the Indian-ID OCR fallback may give "MALE"/"FEMALE".
    sex = str(by_name.get("sex", "") or "").strip().upper()
    gender = {"M": "Male", "F": "Female"}.get(sex[:1]) if sex else None
    return {
        "document_number": by_name.get("document_number", ""),
        "full_name": full_name or None,
        "date_of_birth": by_name.get("date_of_birth") or None,
        "gender": gender,
        "address": None,
        "father_or_spouse_name": None,
    }


def _needs_late_gemini_face(is_simulated, live_str, db_photo_path, face_match_data) -> bool:
    """Whether a late 3-image Gemini call is warranted for the registry legs.

    Narrow gate: real (non-simulated) cloud, a resolved registry photo, and
    at least one registry leg still missing — i.e. the record arrived after
    the parallel phase (late hit) or the local engine is down/missed a leg.
    Simulated mode never re-calls: demo verdicts stay Yellow and no quota
    burns. Pure function (unit-tested).
    """
    if is_simulated or not db_photo_path:
        return False
    try:
        return (face_match_data.get("doc_vs_db_match") is None
                or face_match_data.get("live_vs_db_match") is None)
    except Exception:
        return False


async def _run_screening_pipeline(
    doc_path: Path,
    live_path: Optional[Path],
    officer_id: int,
    officer_unit: str = "BORDER_UNIT_1",
    live_burst: Optional[List[str]] = None,
    audit_context: Optional[dict] = None,
    iris_path: Optional[str] = None,
    iris_eye: str = "left",
    iris_source: str = "none",
) -> dict:
    """Execute the full screening pipeline with parallel local+cloud execution.

    Pipeline order (audit fixes applied):
      0. Document quality gate — fail fast on blurry/dark/low-res
      1. Citizen DB lookup FIRST → retrieve photo_uri for 3-way face (P1 §4)
      2. Parallel: tamper + deepfake(live) + liveness + Gemini(3 images) (P1 §3, P2 §1)
      3. Post-process: checksums, demographics, watchlist
      4. Risk engine (with liveness params)
      5. Persist all module results with honest ok/inconclusive (P1 §5)
    """
    # 0. Document quality gate — soft gate for now (logs + risk, not hard 400)
    # Low-res/blurry webcam captures are common; we flag them Yellow and show
    # recapture guidance in the case report, but still run OCR/tamper so the
    # officer gets a result. Change to hard 400 only after threshold calibration.
    _doc_quality_res = None
    try:
        from pipeline.document_quality import run_document_quality
        _doc_quality_res = run_document_quality(str(doc_path), save_evidence=False)
        if _doc_quality_res.status == "ok" and _doc_quality_res.raw_output.get("gate") == "failed":
            print(f"[document_quality] soft gate: { _doc_quality_res.raw_output.get('issues')} metrics={_doc_quality_res.raw_output.get('metrics')}")
            # Do not raise — let screening continue; risk engine will handle the score
    except Exception as e:
        print(f"[document_quality] gate check failed: {e}")
        _doc_quality_res = None

    # Import pipeline modules
    from pipeline.tamper import run_tamper
    from pipeline.physical_forgery import run_physical_forgery
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
    # Step 0: live-still resolution (shared by every face comparison)
    # ------------------------------------------------------------------
    # When no single live capture is supplied but a burst is available
    # (burst-capture flow), use the middle burst frame as the live still
    # for face matching. Never reuse the document as the "live" frame
    # (that would fabricate a match).
    if live_path:
        live_str = str(live_path)
    elif live_burst and len(live_burst) > 0:
        # Use middle frame of burst — more likely eyes-open than first/last
        mid = live_burst[len(live_burst) // 2]
        live_str = str(mid)
    else:
        live_str = None

    # ------------------------------------------------------------------
    # Step 1: REGISTRY FIRST — fast local OCR pre-pass → citizen lookup →
    # reference photo, BEFORE any face verification runs (three-way fix).
    # The DB photo feeds Gemini as Image 3 AND the local three-way matcher,
    # so document↔live, document↔registry and live↔registry are all real
    # comparisons instead of nulls/guesses.
    # ------------------------------------------------------------------
    db_record = None
    citizen_id = None
    db_photo_path = None
    # Specific reason when the registry legs cannot run (surfaced in the
    # report as `db_pairs_unavailable_reason` instead of a generic label).
    _db_photo_unavailable_reason = None
    hint_key: tuple = (None, None)

    ocr_result = await loop.run_in_executor(None, run_ocr_mrz, str(doc_path))
    try:
        _hint_demographics = _ocr_fields_to_demographics(ocr_result.raw_output)
    except Exception:
        _hint_demographics = {}
    _hint_number = (_hint_demographics or {}).get("document_number", "")
    # The OCR hint rarely yields a document_type; fall back to the MRZ slot.
    _hint_type = next(
        (
            f.get("value")
            for f in (ocr_result.raw_output or {}).get("fields") or []
            if f.get("field_name") == "document_type" and f.get("value")
        ),
        None,
    )
    if not _hint_type:
        _mrz_hint = ((ocr_result.raw_output or {}).get("mrz") or {}).get("fields") or {}
        _mt = str(_mrz_hint.get("document_type") or "").strip().upper()
        if _mt == "P":
            _hint_type = "passport"
        elif _mt.lower() in ("aadhaar", "pan", "voter_id", "passport"):
            _hint_type = _mt.lower()
    if _hint_number and _hint_type:
        hint_key = ((_hint_type or "").strip().lower(), _normalize_doc_number(_hint_number))
        _hint_citizen = await _find_citizen_by_number(hint_key[0], hint_key[1])
        if _hint_citizen is not None:
            citizen_id = _hint_citizen.id
            try:
                db_record = _hint_citizen.to_dict()
            except Exception:
                db_record = None
            if _hint_citizen.photo_uri:
                # Resolver handles local paths AND remote (Supabase signed)
                # URLs via a disk cache; sync call goes to the thread pool.
                try:
                    _resolved, _photo_reason = await loop.run_in_executor(
                        None, _resolve_db_photo, _hint_citizen.photo_uri, citizen_id)
                except Exception:
                    _resolved, _photo_reason = None, "registry_photo_download_failed"
                if _resolved:
                    db_photo_path = _resolved
                elif _photo_reason:
                    _db_photo_unavailable_reason = _photo_reason

    # ------------------------------------------------------------------
    # Step 2: Parallel execution — local CV + Gemini AI + local 3-way
    # ------------------------------------------------------------------

    # Local forensic checks (run in thread pool to avoid blocking)
    tamper_task = loop.run_in_executor(None, run_tamper, str(doc_path))

    # Physical forgery checks (layout/font/photo-frame/print-scan/QR/
    # security print) — document-type aware via the Step-1 OCR hint.
    physical_task = loop.run_in_executor(
        None, run_physical_forgery, str(doc_path), _hint_type, _hint_number or None, True,
    )

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
    # Active challenge — randomized per session, stored for audit
    _challenge_type = None
    if live_burst or live_path:
        try:
            from pipeline.liveness import CHALLENGE_TYPES
            import random as _rand
            _challenge_type = _rand.choice(CHALLENGE_TYPES)
        except Exception:
            _challenge_type = "blink"
    if live_burst and len(live_burst) > 0:
        liveness_task = loop.run_in_executor(None, run_liveness, live_burst, _challenge_type)
    elif live_path:
        liveness_task = loop.run_in_executor(None, run_liveness, [str(live_path)], _challenge_type)
    else:
        from pipeline.common import inconclusive_result as _liveness_inconclusive

        async def _no_liveness():
            return _liveness_inconclusive(
                "liveness",
                "no live capture provided — liveness requires a camera burst; manual review required",
            )

        liveness_task = asyncio.create_task(_no_liveness())

    # Security zones — template/layout check (runs on document alone, no live needed)
    try:
        from pipeline.security_zones import run_security_zones
        security_task = loop.run_in_executor(None, run_security_zones, str(doc_path), "unknown")
    except Exception:
        security_task = None

    # Gemini AI call (also in thread pool) — now WITH the registry photo as
    # Image 3 whenever Step 1 found one, so its doc_vs_db / live_vs_db
    # verdicts are grounded instead of guessed-or-null.
    gemini_task = loop.run_in_executor(
        None, scan_document, str(doc_path), live_str, db_photo_path
    )

    # Local three-way face match (InsightFace, evidence-backed) — all three
    # pairs in one worker: doc↔live, doc↔registry, live↔registry. Runs in
    # parallel with Gemini; authoritative for scoring whenever ok.
    from pipeline.face_match import run_three_way_match as _run_local_three_way

    def _three_way_job():
        try:
            return run_three_way_match(str(doc_path), live_str, db_photo_path, save_evidence=False)
        except Exception as exc:  # noqa: BLE001 — never fail screening on biometrics
            import traceback
            print(f"[three-way] local engine exception ({type(exc).__name__}: {exc}); "
                  f"registry legs need the engine or the late-Gemini fallback")
            traceback.print_exc()
            return {
                "pairs": {}, "completeness": "unavailable",
                "db_pairs_unavailable_reason": f"comparison_failed: {type(exc).__name__}",
                "recapture_requested": False, "recapture_target": None,
                "recapture_reasons": [], "primary": {"similarity": None, "match": None},
            }

    local_three_way_task = loop.run_in_executor(None, _three_way_job)

    # Await all in parallel (OCR already completed in Step 1 and is reused).
    # Security zones is optional — include if available
    _gather_tasks = [tamper_task, physical_task, deepfake_task, liveness_task, gemini_task, local_three_way_task]
    _security_idx = None
    if 'security_task' in locals() and security_task is not None:
        _gather_tasks.append(security_task)
        _security_idx = len(_gather_tasks) - 1
    _gather_results = await asyncio.gather(*_gather_tasks)
    tamper_result, physical_result, deepfake_result, liveness_result, gemini_result, local_three_way = _gather_results[:6]
    security_result = _gather_results[_security_idx] if _security_idx is not None else None
    local_face_result = None  # legacy single-pair slot: superseded by local_three_way

    # Local-engine failure signal: run_three_way_match always returns all
    # three pair slots, so EMPTY pairs means the engine itself blew up
    # (missing buffalo_l pack, broken onnxruntime, ...). Capture it for
    # honest reporting instead of silent N/A legs.
    tw_engine_error = None
    if isinstance(local_three_way, dict) and not (local_three_way.get("pairs") or {}):
        tw_engine_error = local_three_way.get("db_pairs_unavailable_reason") or "comparison_failed"
        print(f"[three-way] local engine produced no pairs ({tw_engine_error})")

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
    # --- Merge the three-way comparison (registry-first) ---
    # Local InsightFace pairs are evidence-backed and authoritative for the
    # registry legs: a local ok-result ALWAYS overwrites Gemini's
    # doc_vs_db / live_vs_db (previously an unevidenced guess could stick).
    # For the live↔doc leg, a real (non-simulated) Gemini verdict keeps
    # precedence as before; the local pair fills in when Gemini is
    # simulated or silent. No live capture → live legs are impossible.
    tw = local_three_way if isinstance(local_three_way, dict) else {}
    tw_pairs = tw.get("pairs") or {}
    tw_live = tw_pairs.get("live_vs_doc") or {}
    tw_docdb = tw_pairs.get("doc_vs_db") or {}
    tw_livedb = tw_pairs.get("live_vs_db") or {}
    pair_sources: dict = {}
    face_match_data = face_match_data or {}

    if live_str is None:
        # Face verification is impossible, not "mismatched" (→ Yellow min).
        face_match_data = {
            **face_match_data,
            "live_vs_doc_match": None,
            "live_vs_db_match": None,
            "live_vs_doc_similarity": None,
            "live_vs_db_similarity": None,
            "similarity_score": None,
        }
        pair_sources.update({"live_vs_doc": "none", "live_vs_db": "none"})
    else:
        gem_sim_live = face_match_data.get("similarity_score")
        gem_match_live = face_match_data.get("live_vs_doc_match")
        if not is_simulated and gem_sim_live is not None:
            pair_sources["live_vs_doc"] = "gemini"
            if tw_live.get("status") == "ok":
                pair_sources["live_vs_doc"] = "gemini+local_agree" if bool(tw_live.get("match")) == bool(gem_match_live) else "gemini+local_disagree"
                face_match_data["local_live_vs_doc_similarity"] = tw_live.get("similarity")
        elif tw_live.get("status") == "ok" and tw_live.get("similarity") is not None:
            face_match_data = {
                **face_match_data,
                "similarity_score": float(tw_live["similarity"]),
                "live_vs_doc_match": bool(tw_live["match"]) if tw_live.get("match") is not None else face_match_data.get("live_vs_doc_match"),
                "live_vs_doc_similarity": float(tw_live["similarity"]),
                "visual_reasoning": face_match_data.get("visual_reasoning") or f"Local biometric verification (InsightFace buffalo_l): cosine similarity {float(tw_live['similarity']):.3f} — {'match' if tw_live.get('match') else 'no match'} at threshold 0.55.",
            }
            pair_sources["live_vs_doc"] = "local"
            gemini_result["face_is_real_via_local"] = True
            face_is_real_via_local = True
        else:
            pair_sources["live_vs_doc"] = "none"
    gemini_result["three_way_face_match"] = face_match_data

    # Registry legs: local evidence wins outright (fixes unevidenced guesses).
    for _key, _pair, _mkey, _skey in (
        ("doc_vs_db", tw_docdb, "doc_vs_db_match", "doc_vs_db_similarity"),
        ("live_vs_db", tw_livedb, "live_vs_db_match", "live_vs_db_similarity"),
    ):
        if _pair.get("status") == "ok":
            face_match_data[_mkey] = bool(_pair["match"]) if _pair.get("match") is not None else None
            face_match_data[_skey] = float(_pair["similarity"]) if _pair.get("similarity") is not None else None
            pair_sources[_key] = "local"
        elif not is_simulated and face_match_data.get(_mkey) is not None:
            pair_sources[_key] = pair_sources.get(_key) or "gemini"
        else:
            face_match_data[_mkey] = None
            face_match_data[_skey] = None
            pair_sources[_key] = pair_sources.get(_key) or "none"
    gemini_result["three_way_face_match"] = face_match_data

    # Face quality gate → recapture signal. The local three-way reports
    # quality failures as inconclusive + recapture_requested (never a fake
    # match/mismatch). Surface that on the 3-way panel (persisted inside the
    # gemini payload) and as top-level response fields so the UI can prompt
    # a recapture. A recapture is actionable only when no trustworthy real
    # face verdict exists from either engine.
    face_quality_block = None
    recapture_requested = False
    recapture_reasons: list = []
    recapture_target = None
    try:
        _warnings: list = []
        for _p in (tw_live, tw_docdb, tw_livedb):
            _warnings.extend(_p.get("warnings") or [])
            if isinstance(_p.get("face_quality"), dict):
                for _side in ("live", "document"):
                    _warnings.extend(((_p["face_quality"].get(_side) or {}).get("warnings") or []))
        _gate = "passed" if (tw_live.get("status") == "ok") else "partial"
        if tw.get("recapture_requested"):
            _gate = "failed"
        face_quality_block = {
            "engine": "insightface_local",
            "gate": _gate,
            "pair_status": {k: (tw_pairs.get(k) or {}).get("status") for k in ("live_vs_doc", "doc_vs_db", "live_vs_db")},
            "warnings": _warnings,
        }
        face_match_data = {**(face_match_data or {}), "face_quality": face_quality_block}
        gemini_result["three_way_face_match"] = face_match_data
        if tw.get("recapture_requested"):
            gem_has_verdict = face_match_data.get("similarity_score") is not None
            if not gem_has_verdict:
                recapture_requested = True
                recapture_reasons = list(tw.get("recapture_reasons") or [])
                recapture_target = tw.get("recapture_target")
                face_match_data = {
                    **(face_match_data or {}),
                    "recapture_requested": True,
                    "recapture_target": recapture_target,
                    "recapture_reasons": recapture_reasons,
                }
                gemini_result["three_way_face_match"] = face_match_data
    except Exception:
        pass

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
    # Step 3: Database demographic cross-check (final demographics)
    # ------------------------------------------------------------------
    # The comparison runs whenever we have TRUSTED extraction (real Gemini OR
    # real local OCR). Simulated demo text never drives a comparison, but a
    # matching real document still gets its verdict. If no extraction could be
    # read, the document cannot be verified → officer does a manual check.
    # The Step-1 registry hit is reused when the final (type, number) key
    # matches the OCR hint; otherwise we re-query (real Gemini can correct
    # a misread hint).
    demographic_result = None
    registry_trust = None
    db_photo_late = False
    norm_type = (doc_type or "").strip().lower()
    if demographics and doc_number and norm_type and norm_type != "unknown":
        final_key = (norm_type, _normalize_doc_number(doc_number))
        citizen = None
        if final_key == hint_key and citizen_id is not None and db_record is not None:
            # Reuse the Step-1 hit (same identity the face pairs used).
            async with async_session() as session:
                result = await session.execute(
                    select(CitizenRegistry).where(CitizenRegistry.id == citizen_id)
                )
                citizen = result.scalar_one_or_none()
                if citizen is None:
                    # Row vanished mid-screening — fall back to a fresh lookup.
                    citizen = await _find_citizen_by_number(final_key[0], doc_number)
                else:
                    try:
                        db_record = citizen.to_dict()
                    except Exception:
                        pass
        else:
            citizen = await _find_citizen_by_number(final_key[0], doc_number)

        # Audit the registry access (reason: screening verification for this document)
        try:
            async with async_session() as _audit_sess:
                _audit_sess.add(AuditLog(
                    actor=f"officer:{officer_id}",
                    action=f"registry_access:screening type:{norm_type} number:{doc_number[:4]}***",
                    entity=f"citizen_lookup:{norm_type}:{_normalize_doc_number(doc_number)}",
                    officer_id=officer_id,
                    request_id=audit_context.get("request_id") if 'audit_context' in locals() and audit_context else "",
                    device_info=f"screening case pending",
                ))
                await _audit_sess.commit()
        except Exception:
            pass

        if citizen is not None:
            citizen_id = citizen.id
            try:
                db_record = citizen.to_dict()
            except Exception:
                pass
            demographic_result = reconcile_demographics(demographics, db_record)
            # Controlled-enrollment trust: an untrusted registry row must
            # not vouch for an identity (risk floors these at Yellow).
            try:
                registry_trust = _registry_trust_for(citizen)
            except Exception:
                registry_trust = {"level": "unverified", "verified": False, "reasons": ["trust evaluation failed"]}
            try:
                demographic_result["registry_trust"] = registry_trust
            except Exception:
                pass
            # Late registry hit: the OCR hint missed but final demographics
            # found a record with a photo AFTER the parallel phase — compute
            # the registry legs now so the comparison is still complete.
            # (Gemini didn't see this photo; pair_sources records that.)
            if not db_photo_path and citizen.photo_uri:
                try:
                    _late_resolved, _late_reason = await loop.run_in_executor(
                        None, _resolve_db_photo, citizen.photo_uri, citizen_id)
                except Exception:
                    _late_resolved, _late_reason = None, "registry_photo_download_failed"
                if _late_resolved:
                    db_photo_path = _late_resolved
                    db_photo_late = True
                elif _late_reason:
                    _db_photo_unavailable_reason = _late_reason
                    try:
                        from pipeline.face_match import run_three_way_match as _late_three_way
                        _late = await loop.run_in_executor(
                            None, _late_three_way, str(doc_path), live_str, db_photo_path, False
                        )
                        _late_pairs = (_late or {}).get("pairs") or {}
                        for _key, _mkey, _skey in (
                            ("doc_vs_db", "doc_vs_db_match", "doc_vs_db_similarity"),
                            ("live_vs_db", "live_vs_db_match", "live_vs_db_similarity"),
                        ):
                            _p = _late_pairs.get(_key) or {}
                            if _p.get("status") == "ok":
                                face_match_data[_mkey] = bool(_p["match"]) if _p.get("match") is not None else None
                                face_match_data[_skey] = float(_p["similarity"]) if _p.get("similarity") is not None else None
                                pair_sources[_key] = "local_late"
                        tw_pairs.update({k: v for k, v in _late_pairs.items() if (v or {}).get("status") == "ok"})
                        gemini_result["three_way_face_match"] = face_match_data
                    except Exception as e:
                        print(f"[three-way] late DB-pair exception {e}")

    # Late-Gemini fallback: the registry record arrived after the parallel
    # phase (or the local engine is down) but the cloud is real and a
    # reference photo is now resolved — give Gemini the 3-image comparison
    # it never got, so the registry legs are measured instead of N/A.
    # The live↔doc leg stays with the primary scan; only missing registry
    # legs are filled, sourced as "gemini_late" (cloud evidence, so the
    # risk engine's local-evidence Red rule still ignores them).
    if _needs_late_gemini_face(is_simulated, live_str, db_photo_path, face_match_data):
        print("[three-way] attempting late Gemini 3-image fallback for registry legs")
        try:
            _late_gem = await loop.run_in_executor(
                None, scan_document, str(doc_path), live_str, db_photo_path)
            if isinstance(_late_gem, dict) and not _late_gem.get("is_simulated"):
                _lg = _late_gem.get("three_way_face_match") or {}
                for _key, _mkey, _skey in (
                    ("doc_vs_db", "doc_vs_db_match", "doc_vs_db_similarity"),
                    ("live_vs_db", "live_vs_db_match", "live_vs_db_similarity"),
                ):
                    if face_match_data.get(_mkey) is None and _lg.get(_mkey) is not None:
                        face_match_data[_mkey] = _lg[_mkey]
                        if _lg.get(_skey) is not None:
                            face_match_data[_skey] = _lg[_skey]
                        pair_sources[_key] = "gemini_late"
                gemini_result["three_way_face_match"] = face_match_data
        except Exception as e:
            print(f"[three-way] late Gemini fallback exception {type(e).__name__}")

    # --- Three-way completeness: honest partial/complete reporting ---
    # Every advertised pair must be traceable to evidence (local), a real
    # cloud verdict (gemini), or an explicit unavailable reason — never a
    # silent null.
    try:
        _computed = sum(1 for k in ("live_vs_doc", "doc_vs_db", "live_vs_db")
                        if face_match_data.get(f"{k}_match") is not None
                        or (k == "live_vs_doc" and face_match_data.get("similarity_score") is not None))
        if live_str is None:
            _expected = 1  # only doc_vs_db can exist without a live still
            _db_reason = None if face_match_data.get("doc_vs_db_match") is not None else (
                "no_registry_match" if citizen_id is None
                else (_db_photo_unavailable_reason or "no_registry_photo"))
        else:
            _expected = 3 if citizen_id is not None and db_photo_path else (1 if citizen_id is None else 2)
            _db_reason = None
            if citizen_id is None:
                _db_reason = "no_registry_match"
            elif not db_photo_path:
                _db_reason = _db_photo_unavailable_reason or "no_registry_photo"
            elif (face_match_data.get("doc_vs_db_match") is None
                    and face_match_data.get("live_vs_db_match") is None
                    and tw_engine_error):
                # Photo was available but the local engine produced nothing
                # (and late-Gemini was ineligible or also silent).
                _db_reason = "local_face_engine_unavailable"
        face_match_data["pair_sources"] = dict(pair_sources)
        face_match_data["comparison_completeness"] = (
            "complete" if _computed >= _expected and _expected == 3
            else ("partial" if _computed > 0 else "unavailable"))
        face_match_data["db_pairs_unavailable_reason"] = _db_reason
        if db_photo_late:
            face_match_data["db_photo_late"] = True
        # Annotate the reasoning with the evidence-backed DB similarities.
        try:
            _extra = []
            if isinstance(face_match_data.get("doc_vs_db_similarity"), (int, float)):
                _extra.append(f"Doc vs DB local {float(face_match_data['doc_vs_db_similarity']):.3f}")
            if isinstance(face_match_data.get("live_vs_db_similarity"), (int, float)):
                _extra.append(f"Live vs DB local {float(face_match_data['live_vs_db_similarity']):.3f}")
            if _extra:
                face_match_data["visual_reasoning"] = (face_match_data.get("visual_reasoning") or "") + " | " + ", ".join(_extra)
        except Exception:
            pass
        gemini_result["three_way_face_match"] = face_match_data
    except Exception:
        pass

    # --- Watchlist check ---
    full_name = (demographics or {}).get("full_name", "")
    watchlist_result = check_watchlist(name=full_name, id_number=doc_number)

    # --- Iris verification (unified person capture) ---
    # iris_path is either an explicit iris_image upload (backward compat) or an
    # eye crop derived server-side from the SAME live burst that feeds face +
    # face-liveness (see screen_document). No second camera is opened.
    iris_result = None
    iris_eye_used = iris_eye if isinstance(iris_eye, str) and iris_eye else "left"
    # iris_source is a pipeline kwarg set by screen_document:
    # "unified_burst_derived" | "separate_upload" | "none"
    if not isinstance(iris_source, str) or not iris_source:
        iris_source = "none"
    try:
        from backend.biometric.iris.provider import get_provider as _get_iris_provider
        _prov_iris_shared = _get_iris_provider("rgb")
    except Exception:
        _prov_iris_shared = None
    if iris_path and citizen_id and _prov_iris_shared is not None:
        try:
            from backend.models import IrisTemplate
            async with async_session() as _iris_sess:
                _r2 = await _iris_sess.execute(select(IrisTemplate).where(IrisTemplate.citizen_id == citizen_id).order_by(IrisTemplate.created_at.desc()).limit(1))
                tmpl = _r2.scalar_one_or_none()
                if tmpl:
                    prov_iris = _prov_iris_shared
                    # Decrypt template
                    import base64
                    try:
                        enc = tmpl.template
                        if ":" in enc:
                            _, b64 = enc.split(":", 1)
                            ref_t = base64.b64decode(b64.encode())
                        else:
                            ref_t = base64.b64decode(enc.encode())
                        ref_m = None
                        if tmpl.mask and ":" in tmpl.mask:
                            _, mb64 = tmpl.mask.split(":", 1)
                            ref_m = base64.b64decode(mb64.encode())
                        elif tmpl.mask:
                            ref_m = base64.b64decode(tmpl.mask.encode())
                    except Exception:
                        ref_t, ref_m = None, None
                    if ref_t:
                        iris_result = prov_iris.verify(iris_path, ref_t, ref_m)
                        # Attach quality + PAD from the SAME capture (never raw bytes).
                        # PAD needs a multi-frame eye burst; the unified flow has one
                        # derived eye crop, so PAD is honestly inconclusive here
                        # (face-burst liveness still guards presentation attacks).
                        # A dedicated eye-burst input can enable full iris PAD later.
                        try:
                            _q = prov_iris.quality(iris_path)
                        except Exception:
                            _q = {"quality": None, "usable": None}
                        try:
                            _pad = prov_iris.liveness([iris_path])
                        except Exception:
                            _pad = {"passed": None}
                        if isinstance(iris_result, dict):
                            iris_result = {
                                **iris_result,
                                "quality": _q,
                                "liveness": _pad if isinstance(_pad, dict) else {"passed": None},
                                "eye": iris_eye_used,
                                "source": iris_source,
                                "provider": getattr(prov_iris, "name", "RGBProvider"),
                                "provider_version": getattr(prov_iris, "version", "1.0-rgb-prototype"),
                            }
                    else:
                        iris_result = {"match": None, "decision": "INCONCLUSIVE", "reason": "template decrypt failed", "eye": iris_eye_used, "source": iris_source}
                else:
                    # Template missing: still assess quality/PAD of the unified eye crop
                    # so the officer gets actionable feedback (not a silent N/A).
                    # Single derived crop → iris PAD inconclusive (see note above).
                    try:
                        _q = _prov_iris_shared.quality(iris_path)
                    except Exception:
                        _q = {"quality": None, "usable": None}
                    try:
                        _pad = _prov_iris_shared.liveness([iris_path])
                    except Exception:
                        _pad = {"passed": None}
                    iris_result = {"match": None, "decision": "INCONCLUSIVE", "reason": "no template enrolled",
                                   "quality": _q, "liveness": _pad if isinstance(_pad, dict) else {"passed": None},
                                   "eye": iris_eye_used, "source": iris_source,
                                   "provider": getattr(_prov_iris_shared, "name", "RGBProvider"),
                                   "provider_version": getattr(_prov_iris_shared, "version", "1.0-rgb-prototype")}
        except Exception as e:
            iris_result = {"match": None, "decision": "INCONCLUSIVE", "reason": str(e)[:80], "eye": iris_eye_used, "source": iris_source}
    elif iris_path and not citizen_id and _prov_iris_shared is not None:
        # Eye crop exists but no registry match: quality/PAD only, no verification.
        try:
            _q = _prov_iris_shared.quality(iris_path)
        except Exception:
            _q = {"quality": None, "usable": None}
        iris_result = {"match": None, "decision": "INCONCLUSIVE", "reason": "no registry record for iris verification",
                       "quality": _q, "liveness": {"passed": None}, "eye": iris_eye_used, "source": iris_source,
                       "provider": getattr(_prov_iris_shared, "name", "RGBProvider"),
                       "provider_version": getattr(_prov_iris_shared, "version", "1.0-rgb-prototype")}
    # If no iris provided, keep None for risk engine
    # Safe public payload (no template bytes ever leave the server)
    iris_verification = None
    if iris_result is not None:
        try:
            _q = iris_result.get("quality")
            _qval = _q.get("quality") if isinstance(_q, dict) else _q
            _qusable = _q.get("usable") if isinstance(_q, dict) else None
            _qissues = _q.get("issues") if isinstance(_q, dict) else None
            _pad = iris_result.get("liveness")
            iris_verification = {
                "captured": True,
                "eye": iris_result.get("eye", iris_eye_used),
                "source": iris_result.get("source", iris_source),
                "match": iris_result.get("match"),
                "distance": iris_result.get("distance"),
                "threshold": iris_result.get("threshold", 0.32),
                "low_confidence": iris_result.get("low_confidence"),
                "decision": iris_result.get("decision"),
                "quality": _qval,
                "quality_usable": _qusable,
                "quality_issues": _qissues,
                "liveness_passed": (_pad or {}).get("passed") if isinstance(_pad, dict) else None,
                "liveness_confidence": (_pad or {}).get("confidence") if isinstance(_pad, dict) else None,
                "provider": iris_result.get("provider", "RGBProvider"),
                "provider_version": iris_result.get("provider_version", "1.0-rgb-prototype"),
                "reason": iris_result.get("reason"),
            }
        except Exception:
            iris_verification = {"captured": True, "eye": iris_eye_used, "source": iris_source,
                                 "match": None, "decision": "INCONCLUSIVE"}

    # ------------------------------------------------------------------
    # Step 4: Risk Engine (with liveness — audit P1 §3)
    # ------------------------------------------------------------------
    face_sim = face_match_data.get("similarity_score")
    face_match_bool = face_match_data.get("live_vs_doc_match")

    # Fairness & bias mitigation: log per-case signals for aggregate audit
    # and flag low-confidence band for manual review (balanced training note:
    # seed data is intentionally diverse across gender/age for demo).
    try:
        from pipeline.fairness import is_low_confidence, log_fairness_case
        _low_conf = is_low_confidence(face_sim)
        # Try to get quality report from liveness or face module
        _quality = None
        try:
            _quality = (liveness_result.raw_output or {}).get("quality") or (face_match_data or {}).get("quality")
        except Exception:
            pass
        log_fairness_case(
            case_id=None,  # will be set after case creation; also logged in-memory for report
            demographics=demographics,
            face_similarity=face_sim,
            face_match=face_match_bool,
            quality_report=_quality,
            low_confidence=_low_conf,
        )
    except Exception:
        pass

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
    # Network failure (cloud_unavailable) is a controlled fallback: local checks
    # continue, but final verdict must be Yellow/Manual Review, never Green.
    is_demo_case = bool(is_simulated)
    is_cloud_unavailable = bool(gemini_result.get("cloud_unavailable"))
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
    # Cloud unavailable always forces at least Yellow, even if local checks are Green
    cloud_unavailable_for_risk = is_cloud_unavailable

    # Evidence-backed registry pairs for the risk engine. Evidence counts
    # as "local" only when every registry leg carrying a verdict came from
    # a local InsightFace ok-run; Gemini guesses and simulated values are
    # "other" so the Red rule ignores them.
    try:
        _local_legs = [s for s in (pair_sources.get("doc_vs_db"), pair_sources.get("live_vs_db"))
                       if s in ("local", "local_late")]
        _verdict_legs = [k for k in ("doc_vs_db_match", "live_vs_db_match")
                         if face_match_data.get(k) is not None]
        _db_evidence = "local" if _verdict_legs and len(_local_legs) >= len(_verdict_legs) else "other"
        db_face_pairs = {
            "doc_vs_db_match": face_match_data.get("doc_vs_db_match"),
            "live_vs_db_match": face_match_data.get("live_vs_db_match"),
            "evidence": _db_evidence,
        }
    except Exception:
        db_face_pairs = None

    # Iris for risk (if provided)
    iris_match_val = (iris_result or {}).get("match") if iris_result else None
    iris_quality_val = (iris_result or {}).get("quality") if iris_result else None
    iris_liveness_val = (iris_result or {}).get("liveness") if iris_result else None
    # Fallback: if iris_result has direct liveness
    if iris_result and "liveness" not in iris_result and "passed" in iris_result:
        iris_liveness_val = iris_result

    risk = assess_risk(
        demographic_result=demographic_result,
        tamper_score=tamper_result.score if tamper_result.status == "ok" else None,
        tamper_status=tamper_result.status,
        physical_score=physical_result.score if physical_result.status == "ok" else None,
        physical_status=physical_result.status,
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
        registry_trust=registry_trust,
        db_face_pairs=db_face_pairs,
        iris_match=iris_match_val,
        iris_quality=iris_quality_val,
        iris_liveness=iris_liveness_val,
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
    # Cloud unavailable (network failure) — controlled fallback, not a halt:
    # local checks continued, but final result must be Yellow/Manual Review.
    if cloud_unavailable_for_risk:
        if risk.verdict == "Green":
            risk.verdict = "Yellow"
        if "CLOUD_UNAVAILABLE_FALLBACK" not in risk.flags:
            risk.flags.append("CLOUD_UNAVAILABLE_FALLBACK")
        # Ensure the recommendation mentions manual review due to cloud
        if not any("cloud" in rec.lower() for rec in risk.recommendations):
            risk.recommendations.append(
                "Cloud AI verification was unavailable due to network/cloud failure — local checks completed, "
                "but final decision requires manual officer review. System did not halt; fallback policy applied."
            )
        # Also ensure at least Yellow
        if risk.verdict == "Green":
            risk.verdict = "Yellow"
    # Face quality recapture: the capture was too poor to match (never a
    # verdict). Flag it explicitly so the officer knows the fix is a
    # recapture, not a mismatch investigation. (Verdict is already ≥Yellow
    # via the inconclusive face status.)
    if recapture_requested:
        if "FACE_QUALITY_RECAPTURE" not in risk.flags:
            risk.flags.append("FACE_QUALITY_RECAPTURE")
        if risk.verdict == "Green":
            risk.verdict = "Yellow"
        detail = "; ".join(recapture_reasons[:3]) if recapture_reasons else "face image quality too poor"
        risk.recommendations.append(
            f"Recapture requested ({recapture_target or 'face image'}): {detail} "
            f"No biometric verdict was produced — retake and re-screen."
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
        "is_demo": bool(is_demo_case),
        "cloud_unavailable": bool(cloud_unavailable_for_risk),
        "cloud_fallback_reason": gemini_result.get("cloud_fallback_reason") if isinstance(gemini_result, dict) else None,
        "registry_trust": (registry_trust or {}).get("level"),
        "three_way_completeness": (face_match_data or {}).get("comparison_completeness"),
        "three_way_sources": (face_match_data or {}).get("pair_sources"),
        "db_photo_late": bool(db_photo_late),
        "face_quality_gate": (face_quality_block or {}).get("gate"),
        "recapture_requested": recapture_requested,
        "iris": {
            "captured": bool((iris_verification or {}).get("captured")) if 'iris_verification' in locals() else False,
            "eye": (iris_verification or {}).get("eye") if 'iris_verification' in locals() else None,
            "source": (iris_verification or {}).get("source") if 'iris_verification' in locals() else None,
            "match": (iris_verification or {}).get("match") if 'iris_verification' in locals() else None,
            "distance": (iris_verification or {}).get("distance") if 'iris_verification' in locals() else None,
            "quality": (iris_verification or {}).get("quality") if 'iris_verification' in locals() else None,
            "decision": (iris_verification or {}).get("decision") if 'iris_verification' in locals() else None,
            "provider": (iris_verification or {}).get("provider") if 'iris_verification' in locals() else None,
            "provider_version": (iris_verification or {}).get("provider_version") if 'iris_verification' in locals() else None,
        },
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
            challenge_type=_challenge_type,
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
            ("physical_forgery", physical_result.score, physical_result.status,
             physical_result.raw_output, physical_result.evidence_uri, False),
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
        # Iris module — persisted so CaseReport/audit can render it without
        # re-running biometrics. Score = Hamming distance (low = good);
        # status inconclusive when no usable verification exists.
        try:
            _iris_mod = iris_verification if 'iris_verification' in locals() else None
            if _iris_mod is not None:
                _imatch = _iris_mod.get("match")
                _idist = _iris_mod.get("distance")
                _iqu = _iris_mod.get("quality_usable")
                if _imatch is True:
                    _istatus, _iscore = "ok", float(_idist) if isinstance(_idist, (int, float)) else 0.0
                elif _imatch is False:
                    _istatus, _iscore = "ok", float(_idist) if isinstance(_idist, (int, float)) else 1.0
                else:
                    _istatus, _iscore = "inconclusive", None
                modules.append(("iris", _iscore, _istatus, dict(_iris_mod), None, False))
        except Exception:
            pass

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
        try:
            _iris_audit = ""
            _iv = iris_verification if 'iris_verification' in locals() else None
            if isinstance(_iv, dict) and _iv.get("captured"):
                _iris_audit = f" iris:{_iv.get('decision') or _iv.get('match')} eye:{_iv.get('eye')} q:{_iv.get('quality')} prov:{_iv.get('provider')}"
        except Exception:
            _iris_audit = ""
        session.add(AuditLog(
            actor=actor,
            action=f"screening_completed:verdict={risk.verdict} unit:{officer_unit}{_iris_audit}{file_hashes_str}",
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
        "iris_verification": iris_verification if 'iris_verification' in locals() else None,
        "face_quality": face_quality_block,
        "recapture_requested": recapture_requested,
        "recapture_target": recapture_target,
        "recapture_reasons": recapture_reasons,
        "tamper": tamper_result.to_json(),
        "physical_forgery": physical_result.to_json(),
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
            "cloud_unavailable": bool(gemini_result.get("cloud_unavailable")),
            "cloud_fallback_reason": gemini_result.get("cloud_fallback_reason"),
            "gemini_status": gemini_status,
            "latency_ms": gemini_result.get("latency_ms"),
            "model_used": gemini_result.get("model_used"),
            "db_photo_available": db_photo_path is not None,
        },
        "cloud_unavailable": bool(gemini_result.get("cloud_unavailable")),
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

    # Iris verification payload for the Biometric Verification panel (safe fields only)
    iris_verification_payload = None
    try:
        _iris_mod = next((m for m in modules if m.module_name == "iris"), None)
        if _iris_mod is not None:
            _raw = _iris_mod.raw_output
            if isinstance(_raw, str):
                try:
                    import json as _j2
                    _raw = _j2.loads(_raw)
                except Exception:
                    _raw = None
            if isinstance(_raw, dict):
                iris_verification_payload = _raw
    except Exception:
        iris_verification_payload = None

    return {
        "case": case.to_dict(),
        "citizen": citizen_data,
        "db_record_found": citizen_data is not None,
        "extracted_fields": [f.to_dict() for f in fields],
        "module_results": [m.to_dict() for m in modules],
        "officer_actions": [a.to_dict() for a in actions],
        "is_demo": is_demo,
        "demo_label": "DEMO ONLY — simulated AI excluded from scoring" if is_demo else None,
        "iris_verification": iris_verification_payload,
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


@app.get("/api/audit/verify", include_in_schema=False)
async def verify_audit_chain(request: Request):
    """Verify the tamper-evident hash chain for the audit log."""
    officer = await _auth(request)
    if officer.get("role") not in ("auditor", "supervisor"):
        raise HTTPException(status_code=403, detail="Access denied: auditor or supervisor required")
    async with async_session() as session:
        result = await session.execute(select(AuditLog).order_by(AuditLog.id.asc()))
        logs = result.scalars().all()
    prev_hash = "0" * 64
    valid = True
    first_broken = None
    for log in logs:
        if log.prev_hash != prev_hash:
            valid = False
            first_broken = log.id
            break
        try:
            import hmac, hashlib, os
            secret = os.environ.get("JWT_SECRET", "sih-hackathon-dev-secret-change-in-prod")
            payload = f"{log.prev_hash}{log.actor}{log.action}{log.entity}".encode()
            expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
            if log.entry_hash and log.entry_hash != expected:
                valid = False
                first_broken = log.id
                break
        except Exception:
            pass
        prev_hash = log.entry_hash or prev_hash
    return {
        "valid": valid,
        "total_entries": len(logs),
        "first_broken_id": first_broken,
        "last_hash": prev_hash,
        "verified_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }


@app.get("/api/audit/access-review", include_in_schema=False)
async def access_review(request: Request, days: int = Query(30, ge=1, le=365)):
    """Periodic access review — aggregate registry and case access by officer (auditor only)."""
    officer = await _auth(request)
    if officer.get("role") != "auditor":
        raise HTTPException(status_code=403, detail="Access denied: auditor role required")
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with async_session() as session:
        # Use naive cutoff for SQLite
        try:
            cutoff_naive = cutoff.replace(tzinfo=None)
        except Exception:
            cutoff_naive = cutoff
        # Aggregate audit logs
        result = await session.execute(select(AuditLog).where(AuditLog.timestamp >= cutoff_naive).order_by(AuditLog.timestamp.desc()))
        logs = result.scalars().all()
    # Aggregate by actor
    from collections import Counter, defaultdict
    by_actor = Counter(log.actor for log in logs)
    by_action = Counter(log.action.split(":")[0] for log in logs)
    # Registry access by officer
    registry_access = defaultdict(int)
    for log in logs:
        if "registry" in log.action or "citizen" in log.entity:
            registry_access[log.actor] += 1
    # Flag anomalous: officers with high registry access vs cases created
    return {
        "period_days": days,
        "total_events": len(logs),
        "by_actor": dict(by_actor),
        "by_action": dict(by_action),
        "registry_access_by_officer": dict(registry_access),
        "alerts": [
            f"High registry access: {actor} accessed {count} citizen records in {days} days — review for misuse"
            for actor, count in registry_access.items() if count > 20
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/fairness/report", include_in_schema=False)
async def get_fairness_report(request: Request, limit: int = Query(200, ge=1, le=1000)):
    """Fairness & bias audit — aggregated face-matching metrics per demographic / env group.

    Access: supervisor or auditor. Returns per-group mean similarity, low-confidence
    rates, and balanceness of the enrollment data so systemic skew can be detected.
    """
    officer = await _auth(request)
    if officer.get("role") not in ("supervisor", "auditor"):
        raise HTTPException(status_code=403, detail="Access denied: supervisor or auditor role required")
    try:
        from pipeline.fairness import get_fairness_report as _get_report
        report = _get_report(limit=limit)
    except Exception as e:
        report = {"error": str(e), "total": 0}
    # Also report registry enrollment balance
    try:
        async with async_session() as session:
            from sqlalchemy import func as _func
            # Gender balance
            g_res = await session.execute(select(CitizenRegistry.gender, _func.count()).group_by(CitizenRegistry.gender))
            gender_counts = {row[0] or "unknown": row[1] for row in g_res.all()}
            # Type balance
            t_res = await session.execute(select(CitizenRegistry.document_type, _func.count()).group_by(CitizenRegistry.document_type))
            type_counts = {row[0]: row[1] for row in t_res.all()}
            report["enrollment_balance"] = {"by_gender": gender_counts, "by_document_type": type_counts}
    except Exception:
        pass
    return report


# ---------------------------------------------------------------------------
# 8. Citizen Registry management — CONTROLLED ENROLLMENT WORKFLOW
#
# The registry is the authoritative reference for demographic & face
# verification. A single-supervisor direct write could make a false identity
# look legitimate, so:
#   * POST /api/citizens creates a PENDING enrollment (never a live row).
#     A DIFFERENT supervisor must approve it (dual approval / four-eyes).
#   * Source verification runs at request time: document checksum, real-image
#     photo check + SHA-256, mandatory source / source_ref / method / reason.
#   * Signed authority imports (HMAC) bypass the queue — the authority
#     signature is the second factor — but are still validated + audited.
#   * Reconciliation endpoints diff the registry on a schedule against the
#     issuing authority and re-verify checksums / photo integrity.
#   * Screening treats non-trusted registry matches as Yellow-floor
#     (UNVERIFIED_REGISTRY_SOURCE); legacy pre-fix rows are grandfathered as
#     `legacy` (Green still possible) but flagged for re-verification.
# ---------------------------------------------------------------------------

_DOC_TYPES = {"aadhaar", "pan", "voter_id", "passport"}
_REGISTRY_FACES_DIR = _PROJECT_ROOT / "samples" / "faces" / "uploads"

# Authority-import signing secret. Dedicated env var preferred; falls back to
# the JWT secret so existing deployments keep working (logged at startup).
_REGISTRY_IMPORT_SECRET = os.environ.get("REGISTRY_IMPORT_SECRET", "").strip()
_REGISTRY_IMPORT_SECRET_FALLBACK = False
if not _REGISTRY_IMPORT_SECRET:
    _REGISTRY_IMPORT_SECRET = _JWT_SECRET
    _REGISTRY_IMPORT_SECRET_FALLBACK = True

# Enrollment sources & verification methods accepted for manual requests.
# `legacy_seed` is never accepted from clients — only set by seed/bootstrap.
_ENROLL_SOURCES = {"verified_enrollment", "authority_import"}
_ENROLL_SOURCE_LABELS = sorted(_ENROLL_SOURCES)


def _require_role(officer: dict, role: str) -> None:
    """Raise 403 unless the authenticated officer has the given role."""
    if officer.get("role") != role:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied: '{role}' role required",
        )


def _require_supervisor_or_reject(officer: dict) -> None:
    if officer.get("role") != "supervisor":
        raise HTTPException(status_code=403, detail="Access denied: 'supervisor' role required")


def _normalize_doc_number(number: str) -> str:
    """Normalize a document number the same way screening lookups do."""
    return (number or "").strip().replace(" ", "").replace("-", "").upper()


def _citizen_identity_clause(doc_type: str, norm_number: str):
    """Case/format-insensitive (type + number) match for CitizenRegistry.

    Legacy rows predate write-path normalization (`'Aadhaar'` vs `'aadhaar'`,
    `'7848 4723 6650'` vs `'784847236650'`), and exact-match lookups miss
    them — surfacing as a false "NO DOCUMENT FOUND IN THE DATABASE".
    Comparing lower(type) and the space/hyphen-stripped, uppercased number
    on BOTH sides keeps those rows matchable. Type scoping is preserved: a
    PAN never matches an Aadhaar holding the same digits.
    """
    from sqlalchemy import func

    norm_type = (doc_type or "").strip().lower()
    norm_num = _normalize_doc_number(norm_number)
    db_number = func.upper(
        func.replace(func.replace(CitizenRegistry.document_number, " ", ""), "-", "")
    )
    return (
        func.lower(CitizenRegistry.document_type) == norm_type,
        db_number == norm_num,
    )


# Registry reference photos: server-local paths, Supabase Storage object
# refs (`img/<object>`, `img://<object>`, bare image filenames when a
# Supabase backend is configured), AND remote http(s) URLs.
#
# Production layout: `citizens_registry.photo_uri` stores the STORAGE PATH
# (e.g. `img/aadhaar_2345.png`), never an expiring signed URL. The backend
# resolves it server-side with SUPABASE_SERVICE_ROLE_KEY (never exposed to
# the browser) via the Storage REST API: short-lived signed URL first,
# authenticated object GET as fallback. Public buckets also work with only
# SUPABASE_URL set. See .env.example.
_REGISTRY_PHOTO_MAX_BYTES = 5_000_000
_REGISTRY_PHOTO_TIMEOUT_S = 8.0
_REGISTRY_PHOTO_IMAGE_EXTS = ("jpg", "jpeg", "png", "webp", "bmp")


def _supabase_photo_config() -> dict:
    """Lazy Supabase Storage config for registry photos (no secrets logged).

    Env:
      SUPABASE_URL — e.g. https://<ref>.supabase.co (required to enable)
      SUPABASE_SERVICE_ROLE_KEY — server-only, private-bucket reads (preferred)
      SUPABASE_ANON_KEY — fallback for public buckets
      SUPABASE_PHOTOS_BUCKET — default bucket (default "img")
      SUPABASE_PHOTO_SIGNED_TTL — signed-URL TTL seconds (default 60)
    """
    base = (os.environ.get("SUPABASE_URL", "") or "").strip().rstrip("/")
    service = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "") or "").strip()
    anon = (os.environ.get("SUPABASE_ANON_KEY", "") or "").strip()
    bucket = (os.environ.get("SUPABASE_PHOTOS_BUCKET", "") or "img").strip().strip("/") or "img"
    try:
        ttl = int(os.environ.get("SUPABASE_PHOTO_SIGNED_TTL", "60") or "60")
    except ValueError:
        ttl = 60
    ttl = max(15, min(ttl, 600))
    return {
        "base": base,
        "service_key": service,
        "anon_key": anon,
        "bucket": bucket,
        "ttl": ttl,
        "configured": bool(base and (service or anon)),
        "private_ok": bool(base and service),
    }


def _parse_storage_ref(photo_uri: str, default_bucket: str) -> Optional[tuple]:
    """Parse a Supabase Storage object ref into (bucket, object_path).

    Accepted prod forms (all stored WITHOUT host or token):
      * "img/photo.jpg" / "img/folder/photo.png" (bucket/object)
      * "img://photo.jpg" / "img://folder/photo.png"
      * "supabase://img/photo.jpg" / "storage://img/photo.jpg"
      * "photo.jpg" (bare image filename → default bucket; only when the
        value is a single path component, so local paths like
        "samples/faces/x.png" never match)
    Returns None for http(s) URLs, local paths, and anything unsafe.
    """
    if not isinstance(photo_uri, str):
        return None
    uri = photo_uri.strip()
    if not uri or len(uri) > 512:
        return None
    lowered = uri.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return None
    # Windows absolute paths and explicit relative/local markers are local.
    if "\\" in uri or uri.startswith(("/", "./", "../")):
        return None
    for prefix in ("supabase://", "storage://", "bucket://"):
        if lowered.startswith(prefix):
            uri = uri[len(prefix):]
            lowered = uri.lower()
            break
    if lowered.startswith("img://"):
        obj = uri[6:].strip().lstrip("/")
        bucket = "img"
    elif lowered.startswith(f"{(default_bucket or 'img').lower()}/"):
        bucket = (default_bucket or "img").strip().strip("/") or "img"
        obj = uri[len(bucket) + 1:].strip().lstrip("/")
    elif "/" not in uri and "." in uri:
        ext = uri.rsplit(".", 1)[-1].lower()[:5]
        if ext not in _REGISTRY_PHOTO_IMAGE_EXTS:
            return None
        bucket = (default_bucket or "img").strip().strip("/") or "img"
        obj = uri
    else:
        return None
    if not obj or ".." in obj.split("/") or obj.startswith("/") or "\\" in obj:
        return None
    obj = "/".join(s for s in obj.split("/") if s not in ("", "."))
    if not obj or len(obj) > 400:
        return None
    return bucket, obj


def _registry_photo_cache_dir() -> Path:
    """Disk cache for downloaded registry photos (keyed by URL hash).

    Remote reference photos (e.g. Supabase Storage signed URLs) are fetched
    once per URL and reused across screenings. Bounded: one stable filename
    per (citizen, URL), rewritten atomically on change.
    """
    import tempfile

    d = Path(tempfile.gettempdir()) / "netraksha_registry_photos"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def _looks_like_image(data: bytes) -> bool:
    """Magic-byte check for PNG / JPEG / BMP / WEBP (never trust extensions)."""
    if not data:
        return False
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if data.startswith(b"\xff\xd8\xff"):
        return True
    if data.startswith(b"BM"):
        return True
    return data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP"


def _supabase_auth_headers(cfg: dict) -> dict:
    """Auth headers for Supabase Storage REST calls (never logged)."""
    key = cfg.get("service_key") or cfg.get("anon_key") or ""
    if not key:
        return {}
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def _http_get_bytes(url: str, headers: Optional[dict] = None) -> tuple:
    """GET a URL with size + Content-Type + magic-byte validation.

    Returns (data, error_reason). Never raises. Shared by direct URL and
    Supabase signed-URL downloads so both paths enforce the same guardrails.
    """
    import urllib.request

    try:
        base_headers = {"User-Agent": "NetrakshaScreening/1.0"}
        if headers:
            base_headers.update(headers)
        req = urllib.request.Request(url, headers=base_headers)
        with urllib.request.urlopen(req, timeout=_REGISTRY_PHOTO_TIMEOUT_S) as resp:
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype and ctype != "application/octet-stream" and not ctype.startswith("image/"):
                return None, f"unexpected Content-Type {ctype!r}"
            data = resp.read(_REGISTRY_PHOTO_MAX_BYTES + 1)
        if not data:
            return None, "empty body"
        if len(data) > _REGISTRY_PHOTO_MAX_BYTES:
            return None, "oversize (>5MB)"
        if not _looks_like_image(data):
            return None, "non-image magic bytes"
        return data, None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}"


def _cache_photo_bytes(data: bytes, citizen_id, cache_key: str, ext: str):
    """Atomically write validated image bytes to the disk cache."""
    ext = (ext or "").lower()[:5]
    if ext not in _REGISTRY_PHOTO_IMAGE_EXTS:
        ext = "jpg"
    cache_dir = _registry_photo_cache_dir()
    cached = cache_dir / f"citizen_{citizen_id}_{cache_key}.{ext}"
    if cached.is_file() and cached.stat().st_size > 0:
        # Callers check the cache first; this covers races.
        return str(cached)
    tmp = cache_dir / f".tmp_{cache_key}.{ext}"
    try:
        tmp.write_bytes(data)
        os.replace(tmp, cached)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
    return str(cached)


def _fetch_supabase_object(bucket: str, object_path: str, citizen_id=None):
    """Download one private/public Storage object via the REST API.

    Order: short-lived signed URL (works for private buckets with the
    service_role key) → authenticated object GET (works for public buckets
    and private buckets when RLS/service key allows). Returns
    (local_path, None) or (None, "registry_photo_download_failed").
    Never raises, never logs key material.
    """
    import json as _json
    import urllib.parse as _parse
    import urllib.request as _request

    cfg = _supabase_photo_config()
    if not cfg["configured"]:
        print("[registry_photo] storage ref needs SUPABASE_URL + key — set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
        return None, "registry_photo_download_failed"
    quoted = _parse.quote(object_path, safe="/")
    ext = (object_path.rsplit(".", 1)[-1] if "." in object_path else "").lower()[:5]
    cache_key = "sb_" + hashlib.sha256(f"{citizen_id}:{bucket}:{object_path}".encode()).hexdigest()[:24]
    cached = _registry_photo_cache_dir() / f"citizen_{citizen_id}_{cache_key}.{ext if ext in _REGISTRY_PHOTO_IMAGE_EXTS else 'jpg'}"
    if cached.is_file() and cached.stat().st_size > 0:
        return str(cached), None

    # 1) Signed URL (private-bucket path; needs service_role).
    if cfg["private_ok"]:
        try:
            sign_url = f"{cfg['base']}/storage/v1/object/sign/{bucket}/{quoted}"
            body = _json.dumps({"expiresIn": cfg["ttl"]}).encode()
            req = _request.Request(
                sign_url, data=body, method="POST",
                headers={**_supabase_auth_headers(cfg), "Content-Type": "application/json",
                         "User-Agent": "NetrakshaScreening/1.0"},
            )
            with _request.urlopen(req, timeout=_REGISTRY_PHOTO_TIMEOUT_S) as resp:
                payload = _json.loads(resp.read(8192).decode("utf-8", "replace"))
            signed = (payload or {}).get("signedURL") or (payload or {}).get("signedUrl") or ""
            if signed:
                full = signed if signed.startswith("http") else f"{cfg['base']}/storage/v1{signed}"
                data, err = _http_get_bytes(full)
                if data:
                    return _cache_photo_bytes(data, citizen_id, cache_key, ext), None
                print(f"[registry_photo] citizen {citizen_id}: signed-URL fetch failed ({err})")
        except Exception as exc:  # noqa: BLE001 — fall through to object GET
            print(f"[registry_photo] citizen {citizen_id}: sign request failed ({type(exc).__name__})")

    # 2) Direct object GET (public buckets; private with adequate key).
    try:
        obj_url = f"{cfg['base']}/storage/v1/object/{bucket}/{quoted}"
        data, err = _http_get_bytes(obj_url, _supabase_auth_headers(cfg) or None)
        if data:
            return _cache_photo_bytes(data, citizen_id, cache_key, ext), None
        print(f"[registry_photo] citizen {citizen_id}: storage GET failed ({err}) — partial comparison")
        return None, "registry_photo_download_failed"
    except Exception as exc:  # noqa: BLE001
        print(f"[registry_photo] citizen {citizen_id}: storage download failed ({type(exc).__name__}) — partial comparison")
        return None, "registry_photo_download_failed"


def _upload_to_supabase_bucket(bucket: str, object_path: str, data: bytes, content_type: str) -> bool:
    """Upload enrollment bytes to Supabase Storage (server-side, never raises).

    Uses POST /storage/v1/object/{bucket}/{object} with x-upsert:true so
    re-approvals overwrite deterministically. Requires SUPABASE_URL +
    SERVICE_ROLE_KEY (private bucket writes). Returns True on 2xx.
    """
    import urllib.request as _request

    try:
        cfg = _supabase_photo_config()
        if not cfg["private_ok"]:
            return False
        if not data or len(data) > _REGISTRY_PHOTO_MAX_BYTES or not _looks_like_image(data):
            return False
        import urllib.parse as _parse

        quoted = _parse.quote(object_path, safe="/")
        url = f"{cfg['base']}/storage/v1/object/{bucket}/{quoted}"
        req = _request.Request(
            url, data=data, method="POST",
            headers={**_supabase_auth_headers(cfg),
                     "Content-Type": content_type or "image/jpeg",
                     "x-upsert": "true",
                     "User-Agent": "NetrakshaScreening/1.0"},
        )
        with _request.urlopen(req, timeout=_REGISTRY_PHOTO_TIMEOUT_S) as resp:
            code = getattr(resp, "status", 200) or 200
            return 200 <= int(code) < 300
    except Exception as exc:  # noqa: BLE001 — approval must never block on storage
        print(f"[registry_photo] upload failed ({type(exc).__name__}) — keeping local staged path")
        return False


def _storage_object_for_enrollment(doc_type: str, doc_number: str, photo_hash: str, suffix: str) -> str:
    """Deterministic Storage object key for an approved enrollment."""
    try:
        safe_num = _normalize_doc_number(doc_number or "unknown") or "unknown"
    except Exception:
        safe_num = "".join(c for c in (doc_number or "unknown").upper() if c.isalnum()) or "unknown"
    safe_type = "".join(c for c in (doc_type or "id").lower() if c.isalnum() or c == "_") or "id"
    short = (photo_hash or "nohash")[:10]
    ext = (suffix or ".jpg").lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    return f"{safe_type}_{safe_num}_{short}{ext}"


def _resolve_db_photo(photo_uri, citizen_id=None):
    """Resolve a citizen `photo_uri` to a local file path for face comparison.

    Handles, in order:
      1. `http(s)` URLs — direct/signed URLs (Supabase hosts get the
         configured apikey attached when available). Downloaded once into
         a disk cache and reused.
      2. Supabase Storage refs — `img/<object>`, `img://<object>`, or a
         bare image filename (resolved into SUPABASE_PHOTOS_BUCKET).
         Requires SUPABASE_URL + key (see `_supabase_photo_config`).
      3. Server-local paths (`samples/faces/x.png`, absolute paths).

    Runs synchronously — callers must use `run_in_executor` so the event
    loop never blocks. Returns `(path, reason)`; never raises:
      * `no_registry_photo` — no URI enrolled on the citizen row
      * `registry_photo_missing_on_server` — local path does not exist
        (or storage ref supplied without Supabase configured)
      * `registry_photo_download_failed` — fetch failed / non-image /
        oversize (degrades to partial comparison, never halts)
    """
    uri = photo_uri.strip() if isinstance(photo_uri, str) else ""
    if not uri:
        return None, "no_registry_photo"
    lowered = uri.lower()

    # --- 1) Remote URL -------------------------------------------------
    if lowered.startswith("http://") or lowered.startswith("https://"):
        try:
            import urllib.parse as _parse

            cfg = _supabase_photo_config()
            extra = None
            try:
                host = (_parse.urlparse(uri).netloc or "").lower()
                base_host = (_parse.urlparse(cfg["base"]).netloc or "").lower() if cfg["base"] else ""
                if cfg["configured"] and base_host and host == base_host:
                    extra = _supabase_auth_headers(cfg) or None
            except Exception:
                extra = None
            key = hashlib.sha256(f"{citizen_id}:{uri}".encode()).hexdigest()[:24]
            stem = uri.split("?", 1)[0].rsplit(".", 1)
            ext = (stem[1] if len(stem) == 2 else "").lower()[:5]
            if ext not in _REGISTRY_PHOTO_IMAGE_EXTS:
                ext = "jpg"
            cached = _registry_photo_cache_dir() / f"citizen_{citizen_id}_{key}.{ext}"
            if cached.is_file() and cached.stat().st_size > 0:
                return str(cached), None
            data, err = _http_get_bytes(uri, extra)
            if not data:
                print(f"[registry_photo] citizen {citizen_id}: download rejected ({err}) — skipping")
                return None, "registry_photo_download_failed"
            return _cache_photo_bytes(data, citizen_id, key, ext), None
        except Exception as exc:  # noqa: BLE001 — degraded, never fatal
            print(f"[registry_photo] citizen {citizen_id}: download failed ({type(exc).__name__}) — partial comparison")
            return None, "registry_photo_download_failed"

    # --- 2) Supabase Storage object ref (prod bucket layout) ------------
    try:
        cfg = _supabase_photo_config()
        ref = _parse_storage_ref(uri, cfg.get("bucket") or "img")
        if ref is not None:
            bucket, object_path = ref
            if not cfg["configured"]:
                print("[registry_photo] storage ref without SUPABASE_URL/keys — cannot fetch; "
                      "set SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY on the backend")
                return None, "registry_photo_missing_on_server"
            return _fetch_supabase_object(bucket, object_path, citizen_id)
    except Exception as exc:  # noqa: BLE001
        print(f"[registry_photo] citizen {citizen_id}: storage resolve failed ({type(exc).__name__})")
        return None, "registry_photo_download_failed"

    # --- 3) Server-local path (dev seeds, migrated absolute paths) -----
    p = Path(uri)
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    if p.is_file():
        return str(p), None
    return None, "registry_photo_missing_on_server"


def _registry_photo_backend_status() -> dict:
    """Non-secret photo-backend summary for /api/health and startup logs."""
    cfg = _supabase_photo_config()
    if cfg["configured"]:
        mode = "supabase_storage+http+local" if cfg["private_ok"] else "supabase_public+http+local"
    else:
        mode = "http+local (set SUPABASE_URL + keys for private bucket refs)"
    return {"mode": mode, "bucket": cfg["bucket"], "configured": cfg["configured"],
            "private_reads": cfg["private_ok"]}


async def _find_citizen_by_number(doc_type: str, doc_number: str):
    """Registry lookup scoped to (type + number). Returns CitizenRegistry or None.

    A PAN must never match an Aadhaar holding the same digits, so every
    attempt is type-scoped. Matching is case/format-insensitive on both
    sides (see `_citizen_identity_clause`) so legacy rows that predate
    write-path normalization still match.
    """
    if not doc_type or not doc_number:
        return None
    async with async_session() as session:
        result = await session.execute(
            select(CitizenRegistry).where(*_citizen_identity_clause(doc_type, doc_number))
        )
        citizen = result.scalar_one_or_none()
        if citizen is None:
            return None
        # Touch the columns we need while bound, then detach.
        try:
            _ = (citizen.id, citizen.photo_uri, citizen.document_type, citizen.document_number)
        except Exception:
            return None
        try:
            session.expunge(citizen)
        except Exception:
            pass
        return citizen


def _validate_enrollment_doc_number(doc_type: str, doc_number: str) -> dict:
    """Source-verification gate: reject document numbers that fail checksums.

    Returns the checksum result dict. Raises 400 when the number is
    affirmatively INVALID. `valid=None` (e.g. passport without MRZ lines —
    cannot be algorithmically verified) is allowed but flagged so the
    approver and reconciliation know a manual authority check is owed.
    """
    try:
        from pipeline.checksums import validate_document_number as _validate
    except Exception:
        return {"valid": None, "method": "validator_unavailable"}
    result = _validate(doc_type, doc_number)
    if result.get("valid") is False:
        raise HTTPException(
            status_code=400,
            detail=f"Source verification failed: {doc_type} number failed "
                   f"{result.get('method', 'checksum')} validation "
                   f"({result.get('detail', 'invalid')}). Verify against the "
                   f"issuing authority before enrolling.",
        )
    return result


def _verify_enrollment_photo(photo_bytes: bytes, filename: str = "") -> str:
    """Verify an enrollment face photo is a real image. Returns its SHA-256.

    Raises 400 for empty, oversized (>5MB), undecodable, or degenerately
    small (<80px on either side) images. A face-presence probe via the local
    InsightFace bundle is attempted when available but is advisory only —
    the hard gate is genuine-image integrity, enforced with Pillow.
    """
    if not photo_bytes:
        raise HTTPException(status_code=400, detail="Photo is required for verified enrollment (face reference).")
    if len(photo_bytes) > 5_000_000:
        raise HTTPException(status_code=400, detail="Photo too large (max 5 MB)")
    try:
        from PIL import Image as _Image
        import io as _io
        img = _Image.open(_io.BytesIO(photo_bytes))
        img.verify()
        img = _Image.open(_io.BytesIO(photo_bytes))
        img.load()
        w, h = img.size
        if min(w, h) < 80:
            raise HTTPException(
                status_code=400,
                detail=f"Photo too small ({w}x{h}); minimum 80px on each side for face verification.",
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Photo is not a decodable image (PNG/JPG/WEBP required).")
    return hashlib.sha256(photo_bytes).hexdigest()


def _registry_trust_for(citizen) -> dict:
    """Classify how much screening may trust a registry row.

    Levels:
      * authority_verified — signed authority import (HMAC second factor).
      * dual_approved     — requested by one supervisor, approved by another.
      * legacy            — pre-fix row (NULL trust columns / legacy_seed):
                            grandfathered for demo continuity, flagged for
                            authority re-verification, Green still possible.
      * unverified        — anything else (self-approved, missing source,
                            single-writer). Screening floors these at Yellow.
    """
    try:
        source = (getattr(citizen, "source", None) or "").strip()
        enrolled = (getattr(citizen, "enrolled_by", None) or "").strip()
        approved = (getattr(citizen, "approved_by", None) or "").strip()
        method = (getattr(citizen, "verification_method", None) or "").strip()
    except Exception:
        source, enrolled, approved, method = "", "", "", ""
    if source == "authority_import" and method == "authority_signed_import":
        return {"level": "authority_verified", "verified": True, "reasons": ["signed authority import"]}
    if enrolled and approved and enrolled != approved:
        return {"level": "dual_approved", "verified": True,
                "reasons": [f"requested by {enrolled}, approved by {approved}"]}
    if not source or source == "legacy_seed":
        return {"level": "legacy", "verified": False,
                "reasons": ["enrolled before dual-approval control — authority re-verification owed"]}
    reasons = []
    if not source:
        reasons.append("missing enrollment source")
    if not approved:
        reasons.append("missing second-supervisor approval")
    if enrolled and approved and enrolled == approved:
        reasons.append("self-approved (requester == approver)")
    return {"level": "unverified", "verified": False, "reasons": reasons or ["untrusted enrollment"]}


def _verify_import_signature(raw_body: bytes, signature: str) -> None:
    """Verify HMAC-SHA256 of the raw import body. Raises 401 on failure."""
    import hmac as _hmac
    sig = (signature or "").strip().lower()
    if not sig:
        raise HTTPException(
            status_code=401,
            detail="Missing X-Import-Signature: authority imports must be "
                   "HMAC-SHA256 signed (see scripts/sign_registry_import.py).",
        )
    expected = _hmac.new(_REGISTRY_IMPORT_SECRET.encode(), raw_body or b"", hashlib.sha256).hexdigest()
    if not _hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401, detail="Invalid import signature (authority authentication failed).")


def _secure_delete_file(path: Optional[Path]) -> bool:
    """Overwrite-with-zeros + unlink. Returns True if the file is gone."""
    try:
        if path is None or not path.is_file():
            return True
        size = path.stat().st_size
        with open(path, "r+b") as f:
            f.write(b"\x00" * size)
            f.flush()
            try:
                import os as _os
                _os.fsync(f.fileno())
            except Exception:
                pass
        path.unlink()
        return not path.is_file()
    except FileNotFoundError:
        return True
    except Exception as e:
        print(f"[retention] failed to securely delete {path}: {e}")
        return False


@app.get("/citizens", include_in_schema=False)
@app.get("/api/citizens")
async def list_citizens(
    request: Request,
    q: Optional[str] = Query(None, description="Search by name or document number"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    reason: Optional[str] = Query(None, description="Reason for search (required for sensitive/broad searches)"),
):
    """List registered citizens with least-privilege scoping and misuse protection."""
    officer = await _auth(request)
    # Sensitive search detection: broad listing, name-only, or bulk
    is_sensitive = False
    sensitivity_reason = ""
    if not q or not q.strip():
        is_sensitive = True
        sensitivity_reason = "broad listing (no query)"
    elif q.strip() and not any(c.isdigit() for c in q):
        # Name-only search without document number
        is_sensitive = True
        sensitivity_reason = "name-only search"
    elif limit > 50:
        is_sensitive = True
        sensitivity_reason = f"bulk search (limit={limit})"
    # Sensitive searches require a reason and are flagged for audit
    if is_sensitive:
        if not reason or len(reason.strip()) < 5:
            raise HTTPException(
                status_code=400,
                detail=f"Sensitive registry search ({sensitivity_reason}) requires a reason (min 5 chars) for audit. Provide ?reason=... and supervisor approval may be required for bulk/name-only queries.",
            )
        # Log the sensitive search as an audit alert (auditor review)
        try:
            async with async_session() as _sess:
                _sess.add(AuditLog(
                    actor=officer.get("username", "unknown"),
                    action=f"registry_search:sensitive:{sensitivity_reason}",
                    entity=f"citizens:q={q} reason:{reason[:80]}",
                    officer_id=int(officer.get("sub", 0)) or None,
                    request_id=request.headers.get("X-Request-ID") or "",
                    device_info=f"UA:{request.headers.get('User-Agent','')[:100]} IP:{request.client.host if request.client else ''}",
                ))
                await _sess.commit()
        except Exception:
            pass
        # For highly sensitive (bulk >100 or name-only), require supervisor approval
        if (limit > 100 or (q and not any(c.isdigit() for c in q) and len(q.strip()) < 4)) and officer.get("role") == "officer":
            raise HTTPException(
                status_code=403,
                detail="Sensitive search requires supervisor approval — please request approval or narrow your search to a specific document number",
            )
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
    source: str = Form("verified_enrollment"),
    source_ref: str = Form(...),
    verification_method: str = Form(...),
    request_reason: str = Form(...),
    photo: UploadFile = File(...),
):
    """Request enrollment of a citizen record (supervisor only).

    Controlled enrollment — this creates a PENDING request, NOT a live
    registry row. A DIFFERENT supervisor must approve it
    (POST /api/citizens/requests/{id}/approve) before the record becomes
    authoritative for screening. Source verification (checksum + real-image
    photo + provenance fields) runs here so bad data never enters the queue.
    """
    officer = await _auth(request)
    _require_role(officer, "supervisor")
    username = officer.get("username", "unknown")
    officer_id = int(officer["sub"])

    # --- validate input ---
    doc_type = (document_type or "").strip().lower()
    if doc_type not in _DOC_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"document_type must be one of: {sorted(_DOC_TYPES)}",
        )

    doc_number = _normalize_doc_number(document_number)
    if not doc_number:
        raise HTTPException(status_code=400, detail="document_number is required")

    name = (full_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="full_name is required")

    if gender and gender.strip().upper() not in ("M", "F", "OTHER"):
        raise HTTPException(status_code=400, detail="gender must be M, F or Other")

    # --- provenance gates (source verification) ---
    src = (source or "").strip().lower()
    if src not in _ENROLL_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"source must be one of: {_ENROLL_SOURCE_LABELS} "
                   f"(how was this identity verified against the issuing authority?)",
        )
    src_ref = (source_ref or "").strip()
    if len(src_ref) < 3:
        raise HTTPException(status_code=400, detail="source_ref is required (min 3 chars): authority batch / file / reference ID.")
    method = (verification_method or "").strip()
    if len(method) < 3:
        raise HTTPException(status_code=400, detail="verification_method is required (min 3 chars): how was this record verified?")
    reason = (request_reason or "").strip()
    if len(reason) < 10:
        raise HTTPException(status_code=400, detail="request_reason is required (min 10 chars): why does this identity belong in the master registry?")

    # --- source verification: document checksum ---
    checksum = _validate_enrollment_doc_number(doc_type, doc_number)
    checksum_unverifiable = checksum.get("valid") is None

    # --- source verification: face photo (mandatory + real-image check) ---
    if not photo or not photo.filename:
        raise HTTPException(status_code=400, detail="Photo is required for verified enrollment (face reference).")
    suffix = Path(photo.filename).suffix.lower() or ".png"
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(status_code=400, detail="Photo must be PNG, JPG/JPEG or WEBP.")
    photo_bytes = await photo.read()
    photo_hash = _verify_enrollment_photo(photo_bytes, photo.filename)
    _REGISTRY_FACES_DIR.mkdir(parents=True, exist_ok=True)
    rel = Path("samples") / "faces" / "uploads" / f"pending_{uuid.uuid4().hex}{suffix}"
    (_PROJECT_ROOT / rel).write_bytes(photo_bytes)
    staged_uri = rel.as_posix()

    async with async_session() as session:
        # Duplicate in the LIVE registry (type-scoped — a PAN must never
        # collide with an Aadhaar holding the same digits).
        existing = await session.execute(
            select(CitizenRegistry).where(
                (CitizenRegistry.document_type == doc_type)
                & (CitizenRegistry.document_number == doc_number)
            )
        )
        if existing.scalar_one_or_none() is not None:
            _secure_delete_file(_PROJECT_ROOT / rel)
            raise HTTPException(
                status_code=409,
                detail=f"A citizen with {doc_type}:{doc_number} already exists in the registry",
            )
        # Duplicate already waiting in the approval queue.
        pending = await session.execute(
            select(RegistryEnrollment).where(
                (RegistryEnrollment.status == "pending")
                & (RegistryEnrollment.action == "create")
                & (RegistryEnrollment.document_type == doc_type)
                & (RegistryEnrollment.document_number == doc_number)
            )
        )
        if pending.scalar_one_or_none() is not None:
            _secure_delete_file(_PROJECT_ROOT / rel)
            raise HTTPException(
                status_code=409,
                detail=f"An enrollment request for {doc_type}:{doc_number} is already pending approval",
            )

        req = RegistryEnrollment(
            action="create",
            status="pending",
            document_type=doc_type,
            document_number=doc_number,
            full_name=name,
            date_of_birth=(date_of_birth or "").strip() or None,
            gender=(gender or "").strip().upper() or None,
            address=(address or "").strip() or None,
            father_or_spouse_name=(father_or_spouse_name or "").strip() or None,
            photo_uri=staged_uri,
            photo_hash=photo_hash,
            source=src,
            source_ref=src_ref,
            verification_method=method,
            request_reason=reason,
            requested_by_id=officer_id,
            requested_by=username,
        )
        session.add(req)
        await session.flush()
        enrollment_id = req.id

        session.add(AuditLog(
            actor=username,
            action="enrollment_requested:create",
            entity=f"enrollment:{enrollment_id}:{doc_type}:{doc_number}",
            officer_id=officer_id,
        ))
        await session.commit()

    msg = f"Enrollment request #{enrollment_id} for {name} ({doc_type.upper()}) is PENDING — a different supervisor must approve it."
    if checksum_unverifiable:
        msg += " Note: document number is not algorithmically verifiable; the approver must confirm it against the issuing authority."
    return {
        "status": "pending",
        "enrollment_id": enrollment_id,
        "message": msg,
    }


class _ReviewNote(BaseModel):
    review_note: Optional[str] = None


@app.get("/api/citizens/requests", include_in_schema=False)
@app.get("/api/citizens/requests/list", include_in_schema=False)
async def list_enrollment_requests(
    request: Request,
    status_filter: Optional[str] = Query(None, alias="status"),
    action: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List controlled-enrollment requests (supervisor + auditor)."""
    officer = await _auth(request)
    if officer.get("role") not in ("supervisor", "auditor"):
        raise HTTPException(status_code=403, detail="Access denied: supervisor or auditor role required")
    async with async_session() as session:
        query = select(RegistryEnrollment).order_by(RegistryEnrollment.created_at.desc())
        if status_filter:
            if status_filter not in ("pending", "approved", "rejected"):
                raise HTTPException(status_code=400, detail="status must be pending|approved|rejected")
            query = query.where(RegistryEnrollment.status == status_filter)
        if action:
            if action not in ("create", "delete"):
                raise HTTPException(status_code=400, detail="action must be create|delete")
            query = query.where(RegistryEnrollment.action == action)
        total = len((await session.execute(query)).scalars().all())
        result = await session.execute(query.limit(limit).offset(offset))
        rows = result.scalars().all()
    return {"requests": [r.to_dict() for r in rows], "count": len(rows), "total": total}


def _require_different_supervisor(officer: dict, req: RegistryEnrollment) -> tuple[int, str]:
    """Enforce four-eyes: approver must be a supervisor other than the requester."""
    _require_role(officer, "supervisor")
    officer_id = int(officer["sub"])
    username = officer.get("username", "unknown")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"Request #{req.id} is already {req.status}")
    if officer_id == req.requested_by_id:
        raise HTTPException(
            status_code=403,
            detail="Separation of duties: the requesting supervisor cannot approve their own enrollment — a different supervisor must review it.",
        )
    return officer_id, username


@app.post("/api/citizens/requests/{enrollment_id}/approve")
async def approve_enrollment(enrollment_id: int, request: Request):
    """Approve a pending enrollment (second supervisor). Creates the live row."""
    officer = await _auth(request)
    async with async_session() as session:
        result = await session.execute(select(RegistryEnrollment).where(RegistryEnrollment.id == enrollment_id))
        req = result.scalar_one_or_none()
        if not req:
            raise HTTPException(status_code=404, detail="Enrollment request not found")
        approver_id, approver = _require_different_supervisor(officer, req)

        if req.action == "create":
            # Re-verify at approval time (data may have changed since request).
            _validate_enrollment_doc_number(req.document_type or "", req.document_number or "")
            dup = await session.execute(
                select(CitizenRegistry).where(
                    *_citizen_identity_clause(req.document_type or "", req.document_number or "")
                )
            )
            if dup.scalar_one_or_none() is not None:
                raise HTTPException(status_code=409, detail="A citizen with this document already exists (created while pending)")
            # Staged photo must still exist and match its recorded hash.
            if not req.photo_uri:
                raise HTTPException(status_code=400, detail="Staged photo missing — request a fresh enrollment")
            staged = (_PROJECT_ROOT / req.photo_uri)
            if not staged.is_file():
                raise HTTPException(status_code=400, detail="Staged photo file is gone — request a fresh enrollment")
            try:
                actual_hash = hashlib.sha256(staged.read_bytes()).hexdigest()
            except Exception:
                raise HTTPException(status_code=400, detail="Cannot read staged photo — request a fresh enrollment")
            if req.photo_hash and actual_hash != req.photo_hash:
                raise HTTPException(status_code=400, detail="Staged photo integrity mismatch (hash changed) — possible tampering; request a fresh enrollment")

            # Production persistence: Render disks are ephemeral, so mirror the
            # staged face to Supabase Storage when configured and point the
            # live row at the storage ref (e.g. "img/aadhaar_X_<hash>.jpg").
            # Dev fallback (no Supabase): keep the local staged path.
            final_photo_uri = req.photo_uri
            try:
                _photo_cfg = _supabase_photo_config()
                if _photo_cfg["private_ok"]:
                    _staged_bytes = staged.read_bytes()
                    _suffix = staged.suffix.lower() or ".jpg"
                    _obj = _storage_object_for_enrollment(
                        req.document_type or "id", req.document_number or "unknown",
                        req.photo_hash or actual_hash, _suffix)
                    _ctype = {".png": "image/png", ".webp": "image/webp"}.get(
                        _suffix, "image/jpeg")
                    if _upload_to_supabase_bucket(_photo_cfg["bucket"], _obj, _staged_bytes, _ctype):
                        final_photo_uri = f"{_photo_cfg['bucket']}/{_obj}"
                        print(f"[registry_photo] enrollment #{req.id}: mirrored to {final_photo_uri}")
                    else:
                        print(f"[registry_photo] enrollment #{req.id}: storage upload failed — keeping local path")
            except Exception as _e:
                print(f"[registry_photo] enrollment #{req.id}: persist warning ({type(_e).__name__}) — keeping local path")

            citizen = CitizenRegistry(
                document_type=req.document_type,
                document_number=req.document_number,
                full_name=req.full_name,
                date_of_birth=req.date_of_birth,
                gender=req.gender,
                address=req.address,
                father_or_spouse_name=req.father_or_spouse_name,
                photo_uri=final_photo_uri,
                source=req.source,
                source_ref=req.source_ref,
                verification_method=req.verification_method,
                photo_hash=req.photo_hash or actual_hash,
                enrolled_by=req.requested_by,
                approved_by=approver,
            )
            session.add(citizen)
            await session.flush()
            req.status = "approved"
            req.approved_by_id = approver_id
            req.approved_by = approver
            req.resulting_citizen_id = citizen.id
            req.decided_at = _utcnow_naive()
            session.add(AuditLog(actor=approver, action="enrollment_approved:create",
                                 entity=f"enrollment:{req.id}:citizen:{citizen.id}",
                                 officer_id=approver_id))
            session.add(AuditLog(actor=approver, action="citizen_registered",
                                 entity=f"citizen:{citizen.id}:{citizen.document_type}:{citizen.document_number}",
                                 officer_id=approver_id))
            await session.commit()
            return {"status": "ok", "citizen": citizen.to_dict(),
                    "message": f"Approved: {citizen.full_name} ({citizen.document_type.upper()}) enrolled by {approver} (requested by {req.requested_by})"}

        elif req.action == "delete":
            # Second-supervisor approval executes the removal.
            target = None
            if req.target_citizen_id:
                res = await session.execute(select(CitizenRegistry).where(CitizenRegistry.id == req.target_citizen_id))
                target = res.scalar_one_or_none()
            if not target:
                raise HTTPException(status_code=404, detail="Target citizen no longer exists")
            detail = f"{target.full_name}:{target.document_type}:{target.document_number}"
            photo_uri = target.photo_uri
            photo_path = None
            if photo_uri:
                try:
                    candidate = (_PROJECT_ROOT / photo_uri).resolve()
                    uploads_dir = (_PROJECT_ROOT / "samples" / "faces" / "uploads").resolve()
                    if uploads_dir in candidate.parents or candidate.parent.resolve() == uploads_dir:
                        photo_path = candidate
                    elif "uploads" in photo_uri:
                        photo_path = candidate
                except Exception:
                    photo_path = None
            await session.delete(target)
            req.status = "approved"
            req.approved_by_id = approver_id
            req.approved_by = approver
            req.decided_at = _utcnow_naive()
            session.add(AuditLog(actor=approver, action="enrollment_approved:delete",
                                 entity=f"enrollment:{req.id}:citizen:{req.target_citizen_id}:{detail}",
                                 officer_id=approver_id))
            session.add(AuditLog(actor=approver, action="citizen_removed",
                                 entity=f"citizen:{req.target_citizen_id}:{detail}",
                                 officer_id=approver_id))
            if photo_uri:
                session.add(AuditLog(actor=approver, action="biometric_retention:deleted",
                                     entity=f"citizen:{req.target_citizen_id}:photo:{photo_uri}",
                                     officer_id=approver_id))
            await session.commit()
            _secure_delete_file(photo_path)
            return {"status": "ok", "deleted_id": req.target_citizen_id,
                    "message": f"Approved deletion of {detail} (requested by {req.requested_by}, approved by {approver})"}
        else:
            raise HTTPException(status_code=400, detail=f"Unknown enrollment action: {req.action}")


@app.post("/api/citizens/requests/{enrollment_id}/reject")
async def reject_enrollment(enrollment_id: int, req_body: _ReviewNote, request: Request):
    """Reject a pending enrollment (second supervisor). Staged photo is purged."""
    officer = await _auth(request)
    note = ((req_body.review_note if req_body else "") or "").strip()
    if len(note) < 3:
        raise HTTPException(status_code=400, detail="review_note is required (min 3 chars): why is this enrollment rejected?")
    async with async_session() as session:
        result = await session.execute(select(RegistryEnrollment).where(RegistryEnrollment.id == enrollment_id))
        req = result.scalar_one_or_none()
        if not req:
            raise HTTPException(status_code=404, detail="Enrollment request not found")
        approver_id, approver = _require_different_supervisor(officer, req)
        staged = (_PROJECT_ROOT / req.photo_uri) if (req.action == "create" and req.photo_uri) else None
        req.status = "rejected"
        req.approved_by_id = approver_id
        req.approved_by = approver
        req.review_note = note
        req.decided_at = _utcnow_naive()
        session.add(AuditLog(actor=approver, action=f"enrollment_rejected:{req.action}",
                             entity=f"enrollment:{req.id}", officer_id=approver_id))
        await session.commit()
    if staged is not None:
        _secure_delete_file(staged)
    return {"status": "ok", "enrollment_id": enrollment_id, "message": f"Request #{enrollment_id} rejected by {approver}"}


class _ImportRecord(BaseModel):
    document_type: str
    document_number: str
    full_name: str
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    address: Optional[str] = None
    father_or_spouse_name: Optional[str] = None
    photo_uri: Optional[str] = None
    photo_hash: Optional[str] = None
    source_ref: Optional[str] = None
    verification_method: Optional[str] = None


class _ImportBody(BaseModel):
    batch_ref: str
    records: List[_ImportRecord]


@app.post("/api/citizens/import")
async def import_authority_citizens(request: Request):
    """Bulk import from the issuing authority (supervisor + HMAC signature).

    The request body must be signed: header `X-Import-Signature` =
    hex(HMAC-SHA256(raw_body, REGISTRY_IMPORT_SECRET)). The authority
    signature is the second factor, so validated records are enrolled
    directly as `authority_import` (still checksum-verified + audited).
    Sign bodies with scripts/sign_registry_import.py.
    """
    officer = await _auth(request)
    _require_role(officer, "supervisor")
    username = officer.get("username", "unknown")
    officer_id = int(officer["sub"])

    raw_body = await request.body()
    _verify_import_signature(raw_body, request.headers.get("X-Import-Signature", ""))
    try:
        payload = json.loads(raw_body.decode() or "{}")
        body = _ImportBody(**payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid import body: {e}")

    batch_ref = (body.batch_ref or "").strip()
    if len(batch_ref) < 3:
        raise HTTPException(status_code=400, detail="batch_ref is required (min 3 chars): authority batch identifier.")
    if not body.records:
        raise HTTPException(status_code=400, detail="records must not be empty (max 500 per batch).")
    if len(body.records) > 500:
        raise HTTPException(status_code=400, detail="Batch too large (max 500 records per import).")

    created, skipped, errors = 0, 0, []
    async with async_session() as session:
        for i, rec in enumerate(body.records):
            try:
                doc_type = (rec.document_type or "").strip().lower()
                if doc_type not in _DOC_TYPES:
                    raise ValueError(f"document_type must be one of {sorted(_DOC_TYPES)}")
                doc_number = _normalize_doc_number(rec.document_number)
                if not doc_number:
                    raise ValueError("document_number is required")
                name = (rec.full_name or "").strip()
                if not name:
                    raise ValueError("full_name is required")
                _validate_enrollment_doc_number(doc_type, doc_number)
                dup = await session.execute(
                    select(CitizenRegistry).where(
                        *_citizen_identity_clause(doc_type, doc_number)
                    )
                )
                if dup.scalar_one_or_none() is not None:
                    skipped += 1
                    continue
                # Photo reference must resolve to a real file when supplied.
                photo_hash = (rec.photo_hash or "").strip() or None
                if rec.photo_uri:
                    cand = (_PROJECT_ROOT / rec.photo_uri)
                    if not cand.is_file():
                        raise ValueError(f"photo_uri not found on server: {rec.photo_uri}")
                    try:
                        actual = hashlib.sha256(cand.read_bytes()).hexdigest()
                    except Exception:
                        raise ValueError(f"cannot read photo_uri: {rec.photo_uri}")
                    if photo_hash and photo_hash != actual:
                        raise ValueError(f"photo_hash mismatch for {doc_number}")
                    photo_hash = actual
                citizen = CitizenRegistry(
                    document_type=doc_type,
                    document_number=doc_number,
                    full_name=name,
                    date_of_birth=(rec.date_of_birth or "").strip() or None,
                    gender=(rec.gender or "").strip().upper() or None,
                    address=(rec.address or "").strip() or None,
                    father_or_spouse_name=(rec.father_or_spouse_name or "").strip() or None,
                    photo_uri=(rec.photo_uri or "").strip() or None,
                    source="authority_import",
                    source_ref=(rec.source_ref or "").strip() or batch_ref,
                    verification_method=(rec.verification_method or "").strip() or "authority_signed_import",
                    photo_hash=photo_hash,
                    enrolled_by=username,
                    approved_by=f"authority:{batch_ref}",
                )
                session.add(citizen)
                await session.flush()
                session.add(AuditLog(
                    actor=username,
                    action="citizen_imported:authority_signed",
                    entity=f"citizen:{citizen.id}:{doc_type}:{doc_number}:batch:{batch_ref}",
                    officer_id=officer_id,
                ))
                created += 1
            except HTTPException as e:
                errors.append({"index": i, "error": e.detail})
            except Exception as e:
                errors.append({"index": i, "error": str(e)})
        session.add(AuditLog(
            actor=username,
            action="authority_import_batch",
            entity=f"batch:{batch_ref}:created:{created}:skipped:{skipped}:errors:{len(errors)}",
            officer_id=officer_id,
        ))
        await session.commit()
    return {"status": "ok", "batch_ref": batch_ref, "created": created,
            "skipped_duplicates": skipped, "errors": errors}


def _reconcile_citizen_row(citizen, authority_by_key: Optional[dict] = None) -> dict:
    """Run all integrity checks for one registry row. Pure (no DB writes)."""
    issues: list[str] = []
    doc_type = (citizen.document_type or "").strip().lower()
    doc_number = (citizen.document_number or "").strip()
    key = (doc_type, _normalize_doc_number(doc_number))
    # 1. checksum
    try:
        from pipeline.checksums import validate_document_number as _validate
        chk = _validate(doc_type, doc_number)
        if chk.get("valid") is False:
            issues.append(f"checksum_invalid:{chk.get('method', '?')}")
    except Exception:
        chk = {"valid": None}
    # 2. photo existence + hash
    if not citizen.photo_uri:
        issues.append("photo_missing")
    else:
        try:
            p = (_PROJECT_ROOT / citizen.photo_uri)
            if not p.is_file():
                issues.append("photo_file_missing")
            elif citizen.photo_hash:
                try:
                    if hashlib.sha256(p.read_bytes()).hexdigest() != citizen.photo_hash:
                        issues.append("photo_hash_mismatch")
                except Exception:
                    issues.append("photo_unreadable")
        except Exception:
            issues.append("photo_unreadable")
    # 3. trust / enrollment provenance
    trust = _registry_trust_for(citizen)
    if trust["level"] == "legacy":
        issues.append("legacy_unreverified:enrolled before dual-approval — re-verify against authority")
    elif trust["level"] == "unverified":
        issues.append(f"unverified_enrollment:{';'.join(trust['reasons'])}")
    # 4. authority snapshot diff (when the operator supplies one)
    if authority_by_key is not None:
        auth = authority_by_key.get(key)
        if auth is None:
            issues.append("missing_in_authority_snapshot")
        else:
            try:
                if (auth.get("full_name", "") or "").strip().lower() != (citizen.full_name or "").strip().lower():
                    issues.append("authority_name_mismatch")
                if (auth.get("date_of_birth", "") or "").strip() != ((citizen.date_of_birth or "").strip()):
                    issues.append("authority_dob_mismatch")
            except Exception:
                pass
    return {"citizen_id": citizen.id, "document_type": doc_type, "document_number": doc_number,
            "trust_level": trust["level"], "issues": issues,
            "status": "ok" if not issues else "needs_review"}


def _parse_authority_snapshot(snapshot) -> Optional[dict]:
    """Normalize an operator-supplied authority export to {(type, number): row}."""
    if not snapshot:
        return None
    if not isinstance(snapshot, list):
        raise HTTPException(status_code=400, detail="authority_snapshot must be a list of {document_type, document_number, full_name, date_of_birth}.")
    if len(snapshot) > 5000:
        raise HTTPException(status_code=400, detail="authority_snapshot too large (max 5000 rows).")
    out = {}
    for row in snapshot:
        try:
            t = str(row.get("document_type", "")).strip().lower()
            n = _normalize_doc_number(str(row.get("document_number", "")))
            if t and n:
                out[(t, n)] = row
        except Exception:
            continue
    return out


async def _build_reconciliation_report(authority_snapshot=None) -> dict:
    """Scan the whole registry and grade every row. Read-only."""
    authority_by_key = _parse_authority_snapshot(authority_snapshot)
    async with async_session() as session:
        result = await session.execute(select(CitizenRegistry).order_by(CitizenRegistry.id.asc()))
        citizens = result.scalars().all()
        pend = await session.execute(select(RegistryEnrollment).where(RegistryEnrollment.status == "pending"))
        pending_count = len(pend.scalars().all())
    rows = [_reconcile_citizen_row(c, authority_by_key) for c in citizens]
    needs = [r for r in rows if r["status"] == "needs_review"]
    by_trust: dict[str, int] = {}
    for c in citizens:
        lvl = _registry_trust_for(c)["level"]
        by_trust[lvl] = by_trust.get(lvl, 0) + 1
    extra = []
    if authority_by_key is not None:
        live_keys = {( (c.document_type or '').strip().lower(), _normalize_doc_number(c.document_number or '')) for c in citizens}
        for k in authority_by_key:
            if k not in live_keys:
                extra.append({"document_type": k[0], "document_number": k[1], "issue": "in_authority_missing_in_registry"})
    return {"generated_at": datetime.now(timezone.utc).isoformat(),
            "total": len(citizens), "ok": len(rows) - len(needs), "needs_review": len(needs),
            "pending_enrollments": pending_count, "by_trust": by_trust,
            "rows": rows, "authority_extra": extra}


@app.get("/api/citizens/reconciliation/report")
async def reconciliation_report(
    request: Request,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    """Integrity + authority-diff report for the master registry (read-only).

    Supervisor/auditor. For a full authority diff, POST to
    /api/citizens/reconciliation/run with an `authority_snapshot` export.
    """
    officer = await _auth(request)
    if officer.get("role") not in ("supervisor", "auditor"):
        raise HTTPException(status_code=403, detail="Access denied: supervisor or auditor role required")
    report = await _build_reconciliation_report(None)
    rows = report["rows"]
    report["rows"] = rows[offset:offset + limit]
    report["limit"], report["offset"] = limit, offset
    return report


@app.post("/api/citizens/reconciliation/run")
async def reconciliation_run(request: Request):
    """Re-verify the registry and persist per-row status (supervisor).

    Optional JSON body: {"authority_snapshot": [...]} — an export from the
    issuing authority to diff against. Each run stamps `last_reconciled_at` /
    `reconciliation_status` and writes an audit entry, giving the periodic
    cadence (e.g. weekly) an auditable trail.
    """
    officer = await _auth(request)
    _require_role(officer, "supervisor")
    username = officer.get("username", "unknown")
    officer_id = int(officer["sub"])
    try:
        body = await request.json()
        snapshot = (body or {}).get("authority_snapshot") if isinstance(body, dict) else None
    except Exception:
        snapshot = None
    authority_by_key = _parse_authority_snapshot(snapshot)
    async with async_session() as session:
        result = await session.execute(select(CitizenRegistry).order_by(CitizenRegistry.id.asc()))
        citizens = result.scalars().all()
        now = _utcnow_naive()
        n_ok, n_review = 0, 0
        for c in citizens:
            check = _reconcile_citizen_row(c, authority_by_key)
            c.reconciliation_status = check["status"]
            c.last_reconciled_at = now
            if check["status"] == "ok":
                n_ok += 1
            else:
                n_review += 1
        session.add(AuditLog(
            actor=username,
            action="registry_reconciled",
            entity=f"registry:total:{len(citizens)}:ok:{n_ok}:needs_review:{n_review}"
                   + (":with_authority_snapshot" if authority_by_key is not None else ":integrity_only"),
            officer_id=officer_id,
        ))
        await session.commit()
    report = await _build_reconciliation_report(snapshot)
    return {"status": "ok", "reconciled": len(citizens), "ok": n_ok,
            "needs_review": n_review, "report": report}


@app.delete("/citizens/{citizen_id}", include_in_schema=False)
@app.delete("/api/citizens/{citizen_id}")
async def delete_citizen(
    citizen_id: int,
    request: Request,
    reason: Optional[str] = Query(None, description="Justification for removal (min 10 chars)"),
):
    """Request removal of a citizen record (supervisor only).

    Controlled removal — creates a PENDING delete request. A DIFFERENT
    supervisor must approve it (POST /api/citizens/requests/{id}/approve)
    before the row and its biometric file are destroyed. Pass
    `?reason=...` (min 10 chars). Direct single-supervisor deletes are
    closed: one malicious removal could blind screening to a real identity.
    """
    officer = await _auth(request)
    _require_role(officer, "supervisor")
    username = officer.get("username", "unknown")
    officer_id = int(officer["sub"])
    justification = (reason or "").strip()
    # Also accept JSON/form body reason for clients that send one.
    if len(justification) < 10:
        try:
            body = await request.json()
            if isinstance(body, dict):
                justification = str(body.get("reason", "") or "").strip()
        except Exception:
            pass
    if len(justification) < 10:
        raise HTTPException(status_code=400, detail="reason is required (min 10 chars) as ?reason=... : why must this identity leave the master registry?")

    async with async_session() as session:
        result = await session.execute(
            select(CitizenRegistry).where(CitizenRegistry.id == citizen_id)
        )
        citizen = result.scalar_one_or_none()
        if not citizen:
            raise HTTPException(status_code=404, detail="Citizen not found")

        pending = await session.execute(
            select(RegistryEnrollment).where(
                (RegistryEnrollment.status == "pending")
                & (RegistryEnrollment.action == "delete")
                & (RegistryEnrollment.target_citizen_id == citizen_id)
            )
        )
        if pending.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail=f"Deletion of citizen {citizen_id} is already pending approval")

        detail = f"{citizen.full_name}:{citizen.document_type}:{citizen.document_number}"
        req = RegistryEnrollment(
            action="delete",
            status="pending",
            document_type=citizen.document_type,
            document_number=citizen.document_number,
            full_name=citizen.full_name,
            target_citizen_id=citizen_id,
            source_ref=f"delete:{citizen_id}",
            request_reason=justification,
            requested_by_id=officer_id,
            requested_by=username,
        )
        session.add(req)
        await session.flush()
        session.add(AuditLog(
            actor=username,
            action="enrollment_requested:delete",
            entity=f"enrollment:{req.id}:citizen:{citizen_id}:{detail}",
            officer_id=officer_id,
        ))
        await session.commit()
        enrollment_id = req.id

    return {
        "status": "pending",
        "enrollment_id": enrollment_id,
        "message": f"Deletion request #{enrollment_id} for citizen {citizen_id} is PENDING — a different supervisor must approve it.",
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
        # Staged pending-enrollment photos are referenced by the queue, not
        # the live registry — never flag (or purge) them as orphans.
        try:
            staged = await session.execute(
                select(RegistryEnrollment.photo_uri).where(
                    (RegistryEnrollment.status == "pending")
                    & (RegistryEnrollment.photo_uri.is_not(None))
                )
            )
            referenced |= {r[0] for r in staged.all() if r[0]}
        except Exception:
            pass
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
# 9. Iris Biometric — enrollment / verification (RGB prototype, NIR stub)
# ---------------------------------------------------------------------------

def _encrypt_template(data: bytes) -> str:
    """Encrypt template for at-rest storage (HMAC + base64, not just plaintext)."""
    import base64, hmac, hashlib
    # Simple envelope: base64(template) + HMAC; in production use Fernet/AES-GCM
    try:
        b64 = base64.b64encode(data).decode()
        sig = hmac.new(_JWT_SECRET.encode(), data, hashlib.sha256).hexdigest()[:16]
        return f"{sig}:{b64}"
    except Exception:
        import base64 as _b64
        return _b64.b64encode(data).decode()

def _decrypt_template(enc: str) -> bytes:
    """Decrypt template."""
    import base64
    try:
        if ":" in enc:
            _, b64 = enc.split(":", 1)
            return base64.b64decode(b64.encode())
        return base64.b64decode(enc.encode())
    except Exception:
        return base64.b64decode(enc.encode())


@app.post("/api/biometric/iris/enroll", include_in_schema=False)
async def enroll_iris(
    request: Request,
    citizen_id: int = Form(...),
    eye: str = Form("left"),
    provider: str = Form("rgb"),
    eye_image: UploadFile = File(...),
):
    """Enroll an iris template for a citizen — supervisor only, eye image is deleted after."""
    officer = await _auth(request)
    _require_role(officer, "supervisor")
    if eye not in ("left", "right"):
        raise HTTPException(status_code=400, detail="eye must be left or right")
    # Validate citizen exists
    async with async_session() as session:
        res = await session.execute(select(CitizenRegistry).where(CitizenRegistry.id == citizen_id))
        citizen = res.scalar_one_or_none()
        if not citizen:
            raise HTTPException(status_code=404, detail="Citizen not found")
    # Process eye image
    eye_bytes = await eye_image.read()
    if len(eye_bytes) > 5_000_000:
        raise HTTPException(status_code=400, detail="Eye image too large (max 5 MB)")
    # Use provider
    try:
        from backend.biometric.iris.provider import get_provider
        prov = get_provider(provider)
        # Need to write to temp file for the provider (expects path or bytes)
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            tmp.write(eye_bytes)
            tmp_path = tmp.name
        result = prov.enroll(tmp_path, eye=eye)
        Path(tmp_path).unlink(missing_ok=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Iris enrollment failed: {e}")
    if not result.get("template"):
        raise HTTPException(status_code=400, detail=f"Iris quality insufficient: {result.get('quality')}")
    # Encrypt and store
    enc_template = _encrypt_template(result["template"])
    enc_mask = _encrypt_template(result["mask"]) if result.get("mask") else None
    async with async_session() as session:
        tmpl = IrisTemplate(
            citizen_id=citizen_id,
            template=enc_template,
            mask=enc_mask,
            quality=float(result["quality"].get("quality", 0.0)) if isinstance(result.get("quality"), dict) else 0.0,
            eye=eye,
            enrolled_by=int(officer["sub"]),
        )
        session.add(tmpl)
        await session.flush()
        tid = tmpl.id
        session.add(AuditLog(
            actor=officer.get("username", "unknown"),
            action=f"iris_enroll:{eye}",
            entity=f"citizen:{citizen_id}:template:{tid}",
            officer_id=int(officer["sub"]),
            request_id=request.headers.get("X-Request-ID") or "",
            device_info=f"provider:{prov.name} version:{prov.version}",
        ))
        await session.commit()
    # Raw eye image is already deleted (temp file) — never stored
    return {
        "template_id": tid,
        "citizen_id": citizen_id,
        "eye": eye,
        "quality": result["quality"],
        "liveness": result.get("liveness", {"passed": None}),
        "provider": prov.name,
        "version": prov.version,
    }


@app.post("/api/biometric/iris/verify", include_in_schema=False)
async def verify_iris(
    request: Request,
    citizen_id: Optional[int] = Form(None),
    case_id: Optional[int] = Form(None),
    eye_image: UploadFile = File(...),
    provider: str = Form("rgb"),
):
    """Verify a probe eye image against a stored template."""
    officer = await _auth(request)
    if not citizen_id and not case_id:
        raise HTTPException(status_code=400, detail="Provide citizen_id or case_id")
    # Resolve citizen_id from case if needed
    if case_id and not citizen_id:
        async with async_session() as session:
            res = await session.execute(select(ScreeningCase).where(ScreeningCase.id == case_id))
            case = res.scalar_one_or_none()
            if not case or not case.citizen_id:
                raise HTTPException(status_code=404, detail="Case has no linked citizen for iris verification")
            citizen_id = case.citizen_id
    # Fetch latest template for this citizen/eye
    async with async_session() as session:
        res = await session.execute(
            select(IrisTemplate).where(IrisTemplate.citizen_id == citizen_id).order_by(IrisTemplate.created_at.desc()).limit(1)
        )
        tmpl = res.scalar_one_or_none()
        if not tmpl:
            raise HTTPException(status_code=404, detail="No iris template enrolled for this citizen")
        ref_template = _decrypt_template(tmpl.template)
        ref_mask = _decrypt_template(tmpl.mask) if tmpl.mask else None
    eye_bytes = await eye_image.read()
    if len(eye_bytes) > 5_000_000:
        raise HTTPException(status_code=400, detail="Eye image too large")
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        tmp.write(eye_bytes)
        tmp_path = tmp.name
    try:
        from backend.biometric.iris.provider import get_provider
        prov = get_provider(provider)
        result = prov.verify(tmp_path, ref_template, ref_mask)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    # Audit
    async with async_session() as session:
        session.add(AuditLog(
            actor=officer.get("username", "unknown"),
            action=f"iris_verify:{'match' if result.get('match') else 'no_match' if result.get('match') is False else 'inconclusive'}",
            entity=f"citizen:{citizen_id}",
            officer_id=int(officer.get("sub")),
        ))
        await session.commit()
    return {
        "match": result.get("match"),
        "distance": result.get("distance"),
        "quality": result.get("quality"),
        "decision": result.get("decision"),
        "provider": prov.name,
        "version": prov.version,
    }


@app.get("/api/biometric/iris/template/{citizen_id}", include_in_schema=False)
async def get_iris_template_status(citizen_id: int, request: Request):
    """Return only whether a template exists and its quality — never the raw template."""
    officer = await _auth(request)
    if officer.get("role") not in ("supervisor", "auditor"):
        raise HTTPException(status_code=403, detail="Supervisor or auditor required")
    async with async_session() as session:
        res = await session.execute(
            select(IrisTemplate).where(IrisTemplate.citizen_id == citizen_id).order_by(IrisTemplate.created_at.desc()).limit(1)
        )
        tmpl = res.scalar_one_or_none()
        if not tmpl:
            return {"template_exists": False, "quality": None, "eye": None}
        return {"template_exists": True, "quality": tmpl.quality, "eye": tmpl.eye, "created_at": tmpl.created_at.isoformat() if tmpl.created_at else None}


# ---------------------------------------------------------------------------
# 10. Evidence files — authenticated + expiring links (no public /evidence)
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
    try:
        from pipeline.face_match import local_engine_status
        face_engine = local_engine_status()
    except Exception as e:
        face_engine = {"initialised": False, "models_present": None,
                       "provider": None, "last_error": f"{type(e).__name__}"}
    try:
        registry_photos = _registry_photo_backend_status()
    except Exception:
        registry_photos = {"mode": "unknown", "bucket": "img", "configured": False,
                           "private_reads": False}
    return {
        "status": "healthy",
        "version": "0.1.0",
        "database": get_engine_info(),
        "face_engine": face_engine,
        "registry_photos": registry_photos,
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

