"""Authentication hardening primitives (no new dependencies).

Covers the "Unsafe Password & Secret Configurations" finding:

* environment-based secrets (APP_ENV / JWT / registry-import strength gates),
* password policy + forced rotation,
* supervisor MFA via TOTP (RFC 6238, stdlib-only — no provisioning QR
  library needed; the manual key + otpauth:// URI are shown instead),
* in-memory sliding-window login / MFA-code rate limiting (single-process;
  see deployment notes for multi-worker setups).

All helpers are pure and unit-tested in tests/test_auth_security.py.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import threading
import time
from collections import deque

# ---------------------------------------------------------------------------
# Environment / secret gates
# ---------------------------------------------------------------------------

DEV_JWT_DEFAULT = "sih-hackathon-dev-secret-change-in-prod"
MIN_SECRET_CHARS = 32


def app_env() -> str:
    """Deployment environment: development | staging | production."""
    return os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "development")).strip().lower()


def is_production() -> bool:
    return app_env() == "production"


def secret_error(secret: str, *, name: str = "JWT_SECRET") -> str | None:
    """Return a human-readable problem with a secret, or None if acceptable.

    Production requires an explicitly configured secret of at least
    MIN_SECRET_CHARS characters that is not the shipped dev default.
    Non-production only warns on the dev default (returned as a string so
    callers can log it uniformly).
    """
    secret = secret or ""
    if not secret or secret == DEV_JWT_DEFAULT:
        if is_production():
            return (f"{name} must be set to a strong random value in production "
                    f"(>= {MIN_SECRET_CHARS} chars). Refusing to start.")
        return (f"Using default {name}. Set a strong value in .env for production.")
    if is_production() and len(secret) < MIN_SECRET_CHARS:
        return (f"{name} is too short for production ({len(secret)} chars, "
                f"need >= {MIN_SECRET_CHARS}). Refusing to start.")
    return None


# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------

MIN_PASSWORD_CHARS = 10


def validate_new_password(password: str) -> None:
    """Enforce the officer password policy. Raises ValueError with the reason."""
    pw = password or ""
    if len(pw) < MIN_PASSWORD_CHARS:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_CHARS} characters.")
    if len(pw) > 256:
        raise ValueError("Password must be at most 256 characters.")
    classes = sum((
        any(c.islower() for c in pw),
        any(c.isupper() for c in pw),
        any(c.isdigit() for c in pw),
        any(not c.isalnum() for c in pw),
    ))
    if classes < 3:
        raise ValueError(
            "Password must contain characters from at least 3 of: lowercase, "
            "UPPERCASE, digits, symbols.")
    lowered = pw.lower()
    for banned in ("password", "netraksha", "border", "officer", "supervisor", "qwerty", "123456"):
        if banned in lowered:
            raise ValueError("Password is too guessable — avoid common words and sequences.")


#: bcrypt hash of a random dummy password — used to verify unknown-user
#: logins in constant-ish time so attackers cannot enumerate usernames by
#: response timing. Generated once offline; it never matches a real login.
DUMMY_HASH = "$2b$12$0cqFtMWkcZzA/0B/BAPssOaLTODk0OfimIdj/ergCYVzt4QuXCYwC"


# ---------------------------------------------------------------------------
# TOTP (RFC 6238, SHA-1, 30s step, 6 digits) — stdlib only
# ---------------------------------------------------------------------------

def generate_totp_secret() -> str:
    """Random 160-bit base32 secret for authenticator enrollment."""
    return base64.b32encode(secrets.token_bytes(20)).decode()


def otpauth_uri(secret: str, username: str, issuer: str = "Netraksha") -> str:
    """otpauth:// URI the officer opens (or copy-pastes) in their app."""
    from urllib.parse import quote

    return (f"otpauth://totp/{quote(issuer)}:{quote(username)}"
            f"?secret={secret}&issuer={quote(issuer)}&digits=6&period=30")


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret, casefold=True)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % 1_000_000).zfill(6)


def totp_at(secret: str, for_time: float | None = None, step: int = 30) -> str:
    """Current TOTP code (for_time injectable for deterministic tests)."""
    counter = int((for_time if for_time is not None else time.time()) // step)
    return _hotp(secret, counter)


def verify_totp(secret: str, code: str, *, window: int = 1,
                for_time: float | None = None, step: int = 30) -> bool:
    """Verify a 6-digit code, accepting ±window steps of clock drift."""
    return match_window(secret, code, max_window=window,
                        for_time=for_time, step=step) is not None


def match_window(secret: str, code: str, *, max_window: int = 10,
                 for_time: float | None = None, step: int = 30) -> int | None:
    """Find the clock-drift offset (in 30s steps) a code belongs to.

    Returns the smallest-|delta| step offset whose code matches, or None if
    the code matches nowhere in ±max_window. Positive = code is from the
    future relative to us (phone ahead) or stale, negative = phone behind —
    either way the absolute value measures clock disagreement. Used ONLY to
    explain failures to the already-authenticated enrolling officer; the
    accept/reject decision always uses verify_totp(window=1).
    """
    digits = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(digits) != 6:
        return None
    try:
        now = int((for_time if for_time is not None else time.time()) // step)
        for radius in range(0, max_window + 1):
            for delta in (0, -radius, radius) if radius else (0,):
                if hmac.compare_digest(_hotp(secret, now + delta), digits):
                    return delta
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# Sliding-window rate limiter (thread-safe, in-memory)
# ---------------------------------------------------------------------------

class RateLimiter:
    """Allow at most max_attempts events per window_s seconds per key."""

    def __init__(self, max_attempts: int = 5, window_s: int = 300):
        self.max_attempts = max_attempts
        self.window_s = window_s
        self._lock = threading.Lock()
        self._hits: dict[str, deque] = {}

    def _prune(self, key: str, now: float) -> deque:
        dq = self._hits.get(key)
        if dq is None:
            dq = self._hits[key] = deque()
        while dq and dq[0] <= now - self.window_s:
            dq.popleft()
        return dq

    def check(self, key: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = time.time()
        with self._lock:
            dq = self._prune(key, now)
            if len(dq) >= self.max_attempts:
                return False, int(dq[0] + self.window_s - now) + 1
            return True, 0

    def register_failure(self, key: str) -> None:
        now = time.time()
        with self._lock:
            self._prune(key, now).append(now)

    def register_success(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def reset(self) -> None:
        """Test hook — clear all buckets."""
        with self._lock:
            self._hits.clear()


def rate_limit_from_env(prefix: str, default_max: int, default_window: int) -> RateLimiter:
    try:
        maximum = int(os.environ.get(f"{prefix}_MAX_ATTEMPTS", default_max))
    except ValueError:
        maximum = default_max
    try:
        window = int(os.environ.get(f"{prefix}_WINDOW_SECONDS", default_window))
    except ValueError:
        window = default_window
    return RateLimiter(max_attempts=max(1, maximum), window_s=max(30, window))


def client_ip(request) -> str:
    """Best-effort client IP behind proxies (X-Forwarded-For aware)."""
    try:
        xff = (request.headers.get("X-Forwarded-For", "") or "").split(",")[0].strip()
        if xff:
            return xff[:64]
        if request.client and request.client.host:
            return str(request.client.host)[:64]
    except Exception:
        pass
    return "unknown"
