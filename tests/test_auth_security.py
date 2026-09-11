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
