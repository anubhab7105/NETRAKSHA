"""Tests for auth hardening (backend/auth_security.py + app wiring).

Default secrets, weak passwords, single-factor supervisors, and unlimited
login guessing must all fail closed — in production loudly (startup), in
every environment at the login boundary.

Run:  python -m pytest tests/test_auth_security.py -v
"""

from __future__ import annotations

import os

import pytest

from backend.auth_security import (
    RateLimiter,
    app_env,
    generate_totp_secret,
    is_production,
    otpauth_uri,
    secret_error,
    totp_at,
    validate_new_password,
    verify_totp,
)


# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------

def test_strong_passwords_accepted():
    validate_new_password("Kiosk-Bravo-2026!")
    validate_new_password("NorthGate#2026-Xy")


def test_weak_passwords_rejected():
    for bad in ["short1A!", "alllowercaseletters", "UPPERCASEONLY123",
                "NoDigitsHere", "Password123!", "officer-2026-XX",
                "netraksha-SECURE-1", "qwerty-ABC-123", "x" * 300]:
        with pytest.raises(ValueError):
            validate_new_password(bad)


# ---------------------------------------------------------------------------
# Secret gates
# ---------------------------------------------------------------------------

def test_secret_gate_dev_default_warns(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert not is_production()
    assert secret_error("sih-hackathon-dev-secret-change-in-prod", name="JWT_SECRET")


def test_secret_gate_production_refuses_default_and_short(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert is_production()
    assert secret_error("sih-hackathon-dev-secret-change-in-prod", name="JWT_SECRET")
    assert secret_error("", name="JWT_SECRET")
    assert secret_error("short-secret", name="JWT_SECRET")


def test_secret_gate_production_accepts_strong(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert secret_error("a" * 32, name="JWT_SECRET") is None
    assert app_env() == "production"


# ---------------------------------------------------------------------------
# TOTP (stdlib) — deterministic vectors via for_time
# ---------------------------------------------------------------------------

def test_totp_roundtrip_and_window():
    secret = generate_totp_secret()
    assert len(secret) >= 32  # 160-bit entropy
    code = totp_at(secret, for_time=1_700_000_000)
    assert verify_totp(secret, code, for_time=1_700_000_000)
    # ±1 step drift tolerated, ±2 steps rejected
    assert verify_totp(secret, code, for_time=1_700_000_000 + 30)
    assert not verify_totp(secret, code, for_time=1_700_000_000 + 61)
    assert not verify_totp(secret, "000000", for_time=1_700_000_000)
    assert not verify_totp(secret, "12", for_time=1_700_000_000)


def test_otpauth_uri_shape():
    uri = otpauth_uri("JBSWY3DPEHPK3PXP", "supervisor1")
    assert uri.startswith("otpauth://totp/")
    assert "secret=JBSWY3DPEHPK3PXP" in uri


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

def test_rate_limiter_blocks_then_recovers():
    rl = RateLimiter(max_attempts=3, window_s=60)
    for _ in range(3):
        allowed, _ = rl.check("k")
        assert allowed
        rl.register_failure("k")
    allowed, retry = rl.check("k")
    assert not allowed and retry > 0
    rl.register_success("k")
    allowed, _ = rl.check("k")
    assert allowed


# ---------------------------------------------------------------------------
# App wiring: token purpose + endpoint presence
# ---------------------------------------------------------------------------

def test_mfa_token_purpose_roundtrip():
    import backend.app as app

    tok = app._create_token(7, "sup1", "supervisor", "HQ", purpose="mfa", expiry_minutes=5)
    payload = app._decode_token(tok)
    assert payload["purpose"] == "mfa" and payload["sub"] == "7"
    sess = app._create_token(7, "sup1", "supervisor", "HQ")
    assert sess != tok
    assert app._decode_token(sess).get("purpose", "session") == "session"


def test_auth_endpoints_registered():
    import backend.app as app

    routes = {(r.path, tuple(sorted(r.methods or ()))) for r in app.app.routes if hasattr(r, "path")}
    paths = {p for p, _ in routes}
    for p in ("/api/auth/mfa/challenge", "/api/auth/change-password",
              "/api/auth/mfa/setup", "/api/auth/mfa/verify", "/api/auth/mfa/disable"):
        assert p in paths, f"missing {p}"


def test_auth_rejects_mfa_token_for_apis():
    import asyncio

    import backend.app as app

    class _Headers(dict):
        pass

    class _Req:
        headers = _Headers()

    async def go():
        tok = app._create_token(7, "sup1", "supervisor", "HQ", purpose="mfa", expiry_minutes=5)
        req = _Req()
        req.headers = {"Authorization": f"Bearer {tok}"}
        with pytest.raises(Exception) as e:
            await app._auth(req)
        assert getattr(e.value, "status_code", None) == 401

    asyncio.run(go())


def test_utcnow_naive_is_naive():
    import backend.app as app

    now = app._utcnow_naive()
    assert now.tzinfo is None


def test_change_password_stores_postgres_safe_datetimes():
    """Regression: tz-aware datetimes crash asyncpg (TIMESTAMP WITHOUT TIME
    ZONE) with a 500 that browsers misreport as CORS. Every DateTime the
    app writes must be naive UTC."""
    import asyncio

    import backend.app as app
    from backend.models import Officer
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    async def go():
        eng = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with eng.begin() as conn:
            from backend.models import Base
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
        old = app.async_session
        app.async_session = maker
        try:
            from passlib.context import CryptContext
            ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
            async with maker() as s:
                s.add(Officer(username="chg1", password_hash=ctx.hash("Old-Pass-2026!"),
                              role="officer", unit="U1", must_change_password=True))
                await s.commit()
            login = await app.login(
                app.LoginRequest(username="chg1", password="Old-Pass-2026!"),
                _AnonReq())
            assert login.must_change_password is True
            await app.change_password(
                app.ChangePasswordRequest(current_password="Old-Pass-2026!",
                                          new_password="New-Pass-2026!"),
                _AuthedReq(login.token))
            async with maker() as s:
                off = (await s.execute(
                    select(Officer).where(Officer.username == "chg1"))).scalar_one()
                assert off.must_change_password is False
                assert off.password_changed_at is not None
                assert off.password_changed_at.tzinfo is None
            # New password verifies (rotation actually took effect).
            login2 = await app.login(
                app.LoginRequest(username="chg1", password="New-Pass-2026!"),
                _AnonReq())
            assert login2.token
        finally:
            app.async_session = old
            await eng.dispose()

    asyncio.run(go())


class _AnonReq:
    headers = {}
    client = None


class _AuthedReq:
    def __init__(self, token):
        self.headers = {"Authorization": f"Bearer {token}"}
        self.client = None


def test_mfa_setup_issues_qr_and_verify_loop():
    """Full enrollment: setup issues a scannable QR + key, and a code from
    that key verifies (catches secret round-trip / encoding regressions)."""
    import asyncio
    import base64

    import backend.app as app
    from backend.models import Officer
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    async def go():
        eng = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with eng.begin() as conn:
            from backend.models import Base
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
        old = app.async_session
        app.async_session = maker
        try:
            from passlib.context import CryptContext
            ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
            async with maker() as s:
                s.add(Officer(username="supqr", password_hash=ctx.hash("Old-Pass-2026!"),
                              role="supervisor", unit="HQ"))
                await s.commit()
            login = await app.login(
                app.LoginRequest(username="supqr", password="Old-Pass-2026!"),
                _AnonReq())
            assert login.token
            setup = await app.mfa_setup(_AuthedReq(login.token))
            assert len(setup["manual_key"]) >= 32
            assert setup["otpauth_uri"].startswith("otpauth://totp/")
            assert setup["qr_data_uri"].startswith("data:image/png;base64,")
            raw = base64.b64decode(setup["qr_data_uri"].split(",", 1)[1])
            assert raw[:8] == b"\x89PNG\r\n\x1a\n"  # real PNG, not an empty stub
            code = totp_at(setup["manual_key"])
            out = await app.mfa_verify(app.MfaVerifyRequest(code=code),
                                       _AuthedReq(login.token))
            assert out["status"] == "ok"
            async with maker() as s:
                off = (await s.execute(
                    select(Officer).where(Officer.username == "supqr"))).scalar_one()
                assert off.totp_enabled is True
        finally:
            app.async_session = old
            await eng.dispose()

    asyncio.run(go())


def test_unhandled_errors_stay_json():
    """A crashing endpoint must still return JSON (via CORS middleware), so
    browsers never again misreport a 500 as a CORS failure."""
    import asyncio

    import backend.app as app
    from fastapi.responses import JSONResponse

    async def go():
        class _Req:
            method = "POST"
            url = type("U", (), {"path": "/api/auth/change-password"})()

        resp = await app._unhandled_exception_handler(_Req(), RuntimeError("boom"))
        assert isinstance(resp, JSONResponse)
        assert resp.status_code == 500
        import json
        assert "detail" in json.loads(resp.body.decode())

        http_resp = await app._unhandled_exception_handler(
            _Req(), app.HTTPException(status_code=403, detail="NOPE"))
        assert http_resp.status_code == 403

    asyncio.run(go())
