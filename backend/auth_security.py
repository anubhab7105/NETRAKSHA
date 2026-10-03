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





DEV_JWT_DEFAULT = "sih-hackathon-dev-secret-change-in-prod"
MIN_SECRET_CHARS = 32

PLACEHOLDER_MARKERS = (
    "change-me", "changeme", "your-", "your_", "test", "example",
    "placeholder", "secret-here", "password", "123456", "abcdef",
)


def looks_placeholder(secret: str) -> bool:
    """True when a secret is an obvious template/placeholder value."""
    lowered = (secret or "").strip().lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def active_secret(name: str = "JWT_SECRET") -> str:
    """Return the configured secret, failing closed in production.

    Non-production keeps the shipped dev default (out-of-the-box demo),
    but production raises RuntimeError when the secret is missing, too
    short, or still the public dev default — so a forged session can
    never be minted from a misconfigured install.
    """
    secret = os.environ.get(name, "")
    if not secret and name == "JWT_SECRET":
        secret = DEV_JWT_DEFAULT
    problem = secret_error(secret, name=name)
    if problem and is_production():
        raise RuntimeError(f"[security] {problem}")
    return secret or DEV_JWT_DEFAULT


def audit_secret() -> str:
    """Domain-separated HMAC key for the audit hash chain (no key reuse).

    Derived as HKDF-SHA256(JWT_SECRET, info="netraksha-audit-log-v1") so a
    JWT-signing key compromise does not silently extend to audit forgery
    and vice versa. Fails closed in production like active_secret().
    """
    master = active_secret("JWT_SECRET").encode()
    info = b"netraksha-audit-log-v1"
    prk = hmac.new(b"\x00" * 32, master, hashlib.sha256).digest()
    okm = hmac.new(prk, info + b"\x01", hashlib.sha256).hexdigest()
    return okm


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
    if looks_placeholder(secret):
        if is_production():
            return (f"{name} looks like a placeholder/template value. "
                    f"Generate a real secret and refusing to start until replaced.")
        return (f"Using placeholder-like {name}. Replace it before any production use.")
    if is_production() and len(secret) < MIN_SECRET_CHARS:
        return (f"{name} is too short for production ({len(secret)} chars, "
                f"need >= {MIN_SECRET_CHARS}). Refusing to start.")
    return None






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





DUMMY_HASH = "$2b$12$0cqFtMWkcZzA/0B/BAPssOaLTODk0OfimIdj/ergCYVzt4QuXCYwC"
_DUMMY_HASH_RUNTIME = None


def dummy_hash() -> str:
    """Per-process unknown-user hash (timing-oracle + precomputation defense).

    Generated lazily once per process at full bcrypt cost so unknown-user
    logins cost the same as real verifications. Falls back to the static
    constant if hashing is unavailable.
    """
    global _DUMMY_HASH_RUNTIME
    if _DUMMY_HASH_RUNTIME is None:
        try:
            _DUMMY_HASH_RUNTIME = password_context().hash("netraksha-unknown-user-dummy-secret")
        except Exception:
            _DUMMY_HASH_RUNTIME = DUMMY_HASH
    return _DUMMY_HASH_RUNTIME


def _password_context():
    """Shared bcrypt context (built once — per-call construction is CPU DoS)."""
    from passlib.context import CryptContext

    return CryptContext(schemes=["bcrypt"], deprecated="auto")


_PWD_CTX = None


def password_context():
    """Process-wide shared CryptContext for bcrypt verify/hash."""
    global _PWD_CTX
    if _PWD_CTX is None:
        _PWD_CTX = _password_context()
    return _PWD_CTX


def verify_password_hash(plain: str, hashed: str) -> bool:
    """Verify a password, returning False (never raising) on corrupt hashes."""
    try:
        return password_context().verify(plain or "", hashed or "")
    except Exception:
        return False


def hash_password(plain: str) -> str:
    """Hash a new password with bcrypt."""
    return password_context().hash(plain or "")






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
    """Best-effort client IP behind proxies (X-Forwarded-For aware).

    X-Forwarded-For is only trusted when TRUST_PROXY=1 is set explicitly
    (app runs behind a known reverse proxy that sanitises the header).
    Otherwise the direct socket peer is used, so a client cannot spoof
    its IP to bypass login throttling or poison audit logs.
    """
    try:
        trust_proxy = os.environ.get("TRUST_PROXY", "").lower() in ("1", "true", "yes")
        if trust_proxy:
            xff = (request.headers.get("X-Forwarded-For", "") or "").split(",")[0].strip()
            if xff:
                return xff[:64]
        if request.client and request.client.host:
            return str(request.client.host)[:64]
    except Exception:
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# At-rest encryption for secrets (audit C5/C6): TOTP + iris templates.
# Fernet (AES-128-CBC + HMAC-SHA256) via the `cryptography` package.
# Keys are never reused directly: the configured master secret is
# domain-separated per purpose with SHA-256 before urlsafe-base64 encoding
# into a 32-byte Fernet key, so JWT-signing compromise does not silently
# extend to TOTP/iris decryption and vice versa.
# Wire format is "enc:v1:<fernet-token>". Legacy plaintext (TOTP) and
# legacy "sig:b64" (iris HMAC encoding) values are still *read* so existing
# dev databases keep working, but all new writes use Fernet.
# ---------------------------------------------------------------------------

_FERNET_CACHE: dict[tuple[str, str], object] = {}


def _derive_fernet_key(master: str, purpose: str) -> str:
    """Derive a Fernet-compatible key from a master secret (domain-separated)."""
    import base64 as _b64
    import hashlib as _hl

    digest = _hl.sha256(f"{purpose}:{master}".encode()).digest()
    return _b64.urlsafe_b64encode(digest).decode()


def fernet_for(purpose: str, env_var: str):
    """Return a Fernet instance for (purpose, env_var), derived from env or JWT secret.

    Example: fernet_for("totp", "TOTP_ENC_KEY") prefers TOTP_ENC_KEY and falls
    back to a domain-separated derivation of JWT_SECRET (with no raw key reuse).
    Raises RuntimeError when `cryptography` is unavailable.
    """
    cache_key = (purpose, env_var)
    if cache_key in _FERNET_CACHE:
        return _FERNET_CACHE[cache_key]
    try:
        from cryptography.fernet import Fernet as _Fernet
    except Exception as exc:
        raise RuntimeError(
            "cryptography package required for at-rest encryption "
            "(pip install cryptography). Refusing to store secrets in plaintext."
        ) from exc
    master = (os.environ.get(env_var, "") or "").strip() or active_secret("JWT_SECRET")
    key = _derive_fernet_key(master, f"netraksha-{purpose}-v1")
    fern = _Fernet(key.encode())
    _FERNET_CACHE[cache_key] = fern
    return fern


def _is_encrypted_value(stored: str) -> bool:
    return isinstance(stored, str) and stored.startswith("enc:v1:")


def encrypt_str_for_storage(plain: str, *, purpose: str, env_var: str) -> str:
    """Encrypt a short string (e.g. TOTP base32 secret) for DB storage."""
    text = plain or ""
    if _is_encrypted_value(text):
        return text
    token = fernet_for(purpose, env_var).encrypt(text.encode()).decode()
    return f"enc:v1:{token}"


def decrypt_str_from_storage(stored: str | None, *, purpose: str, env_var: str) -> str:
    """Decrypt a value written by encrypt_str_for_storage.

    Legacy plaintext (no "enc:v1:" prefix) is returned as-is so pre-encryption
    rows keep verifying; corrupted Fernet payloads raise ValueError so callers
    fail closed instead of accepting tampered secrets.
    """
    if not stored:
        return ""
    if not _is_encrypted_value(stored):
        return stored
    try:
        return fernet_for(purpose, env_var).decrypt(stored[len("enc:v1:"):].encode()).decode()
    except Exception as exc:
        raise ValueError("Stored secret failed integrity check.") from exc


def encrypt_bytes_for_storage(data: bytes, *, purpose: str, env_var: str) -> str:
    """Encrypt raw bytes (e.g. iris template) for a Text column."""
    import base64 as _b64

    raw = bytes(data or b"")
    token = fernet_for(purpose, env_var).encrypt(_b64.b64encode(raw)).decode()
    return f"enc:v1:{token}"


def decrypt_bytes_from_storage(stored: str | bytes | None, *, purpose: str, env_var: str) -> bytes:
    """Decrypt a value written by encrypt_bytes_for_storage (legacy raises)."""
    import base64 as _b64

    if stored is None:
        raise ValueError("Stored template is missing.")
    text = stored if isinstance(stored, str) else stored.decode()
    if not _is_encrypted_value(text):
        raise ValueError("Legacy non-encrypted template envelope.")
    try:
        inner = fernet_for(purpose, env_var).decrypt(text[len("enc:v1:"):].encode())
        return _b64.b64decode(inner)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Stored template failed integrity check.") from exc


def encrypt_totp_secret(plain: str) -> str:
    """Encrypt a TOTP secret for Officer.totp_secret (audit C6)."""
    return encrypt_str_for_storage(plain, purpose="totp", env_var="TOTP_ENC_KEY")


def decrypt_totp_secret(stored: str | None) -> str:
    """Decrypt Officer.totp_secret, accepting legacy plaintext rows."""
    return decrypt_str_from_storage(stored, purpose="totp", env_var="TOTP_ENC_KEY")
