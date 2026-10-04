# API & Authentication

## Authentication & Authorization


`backend/auth_security.py:1` · `backend/app.py:532`

| Concern | Implementation |
|---|---|
| **Passwords** | `passlib[bcrypt]` only (`bcrypt==4.0.1`); SHA-256 fallback removed. Unknown users dummy-verified against `DUMMY_HASH` (`backend/auth_security.py:97`) so timing reveals nothing. Policy: **≥ 10 chars, 3/4 classes** (lower/upper/digit/symbol), ≤ 256, bans `password`/`netraksha`/`border`/`officer`/`supervisor`/`qwerty`/`123456`. |
| **JWT** | `PyJWT` (`HS256`), `purpose=session` (default, 8 h) or `purpose=mfa` (5 min step-up). `jti` = `session_id`. `_create_token` / `_decode_token` (`backend/app.py:118`). `JWT_SECRET` ≥ 32 chars in prod (`secret_error` — `backend/auth_security.py:44`) else fail-fast. |
| **MFA (supervisors)** | TOTP RFC 6238 (SHA-1, 30 s step, 6 digits, `window=1` accept, `window=10` drift hint) — stdlib only (`backend/auth_security.py:104`). Enrollment: `POST /api/auth/mfa/setup` → QR `data:image/png` + `manual_key` + `otpauth://` URI; confirm `POST /api/auth/mfa/verify`; disable `POST /api/auth/mfa/disable`. |
| **Forced rotation** | `must_change_password=True` on all seeded accounts and on bootstrap admin; `_auth` (`backend/app.py:532`) returns **403 `PASSWORD_CHANGE_REQUIRED`** until `POST /api/auth/change-password`. `mfa_setup_required` similarly gates supervisors via **403 `MFA_SETUP_REQUIRED`**. |
| **Rate limiting** | In-memory sliding-window `RateLimiter` (`backend/auth_security.py:167`) per IP **and** per username for login, per `officer_id` for MFA codes. Defaults `5 / 300 s` (`LOGIN_RATE_LIMIT_*`, `MFA_RATE_LIMIT_*`), env-tunable. 429 with `Retry-After`. |
| **RBAC** | `officer` — owns own cases, can `clear`/`escalate` but **never `deny`**; `supervisor` — unit-scoped (`BORDER_UNIT_1`/`BORDER_UNIT_2`/`HQ`), can `deny`, enroll/approve registry; `auditor` — read-only (`cases`/`audit`). Override needs `reason ≥ 3` + `version`/`If-Match`; decided → **409**. |
| **Secrets gates** | `APP_ENV=production` fails fast on default/short `JWT_SECRET` and on missing `BOOTSTRAP_ADMIN_USER`/`PASS`; `REGISTRY_IMPORT_SECRET` falls back to `JWT_SECRET` with warning. |

**Login flow:**

```
POST /api/auth/login {username, password}
  ├─ TOTP not enrolled + supervisor → 200 {must_change_password?, mfa_setup_required:true, token}
  ├─ TOTP enrolled → 200 {mfa_required:true, mfa_token (purpose=mfa, 5 min)}
  │                    └─ POST /api/auth/mfa/challenge {mfa_token, code} → 200 {token}
  └─ otherwise → 200 {token, officer_id, username, role}
```

Bare aliases (`/auth/login`, `/screen`, `/cases`, `/audit`) exist but canonical is `/api/*`.

---

## API Reference


Base URL: `http://127.0.0.1:8000` (dev) or `https://api.netraksha.xyz` (prod). All `/api/*` except login require `Authorization: Bearer <JWT>`.

### Auth

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/login` | Authenticate; may return `mfa_token` for step-up |
| `POST` | `/api/auth/mfa/challenge` | Complete MFA login with TOTP `code` |
| `POST` | `/api/auth/change-password` | Rotate password (clears `must_change_password`) |
| `POST` | `/api/auth/mfa/setup` | Begin TOTP enrollment (supervisor) — returns QR + manual key |
| `POST` | `/api/auth/mfa/verify` | Confirm enrollment with `code` |
| `POST` | `/api/auth/mfa/disable` | Disable own MFA (password + code) |
| `POST` | `/api/auth/logout` | Audit-logged logout (JWT is stateless) |

### Screening

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/screen` | **Multipart** `document_image*` + `live_capture?` + `live_frames[]?` + `iris_image?` + `iris_eye?` (`auto`/`left`/`right`) + `idempotency_key?`. **Requires `Idempotency-Key` header** (`^[A-Za-z0-9\-_:.]{8,128}$`, UUID v4 recommended). Returns `{case_id, document_type, risk_assessment{verdict,risk_score}, module_results[], extracted_fields[], face_verification{three_way}, is_demo, provenance, deduplicated?}`. Same key+session+input → replay `deduplicated:true`; same key+different → **422**; in-flight → **409**; same input+different key (10 min) → replay `duplicate_of_key`. |

Iris is **unified** with the person capture: when `iris_image` is absent but a burst exists, the server derives the best eye crop from the middle burst frame (`iris_derived`, eye quality ≥ 0.5) — no second camera needed.

Document quality gate: both document and crop are checked (Laplacian blur / brightness) — low quality returns `document_quality_failed` with `recapture_reasons`.

### Cases & Overrides

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/cases` | Filterable queue (`?verdict=&status=&unit=&officer_id=&limit=&offset=`) — unit-scoped for supervisors |
| `GET` | `/api/cases/{id}` | Full case report (fields + module results + provenance + actions) |
| `POST` | `/api/cases/{id}/override` | `{action: clear|deny|escalate, reason: ≥3 chars, version?}` — optimistic locking via `version` / `If-Match` |

### Audit & Evidence

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/audit` | Append-only trail with filters (`?actor=&action=&entity=&limit=&offset=`) |
| `GET` | `/api/audit/verify` | Hash-chain integrity check |
| `GET` | `/api/fairness/report` | In-memory fairness ledger |
| `GET` | `/api/evidence/token/{filename}?expires_in=` | Mint signed URL token for an evidence file (`expires_in` 30–`EVIDENCE_TOKEN_MAX_TTL` default 3600 s; over-max → 422) |
| `GET` | `/api/evidence/view?token=` | Serve evidence via short-lived signed token (no auth header needed) |
| `GET` | `/api/evidence/{filename}` | Authenticated direct fetch (case ownership enforced) |

### Registry (controlled enrollment)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/registry/enroll` | Supervisor requests `create`/`delete` — enters `pending` queue |
| `GET` | `/api/registry/enrollments` | List enrollments (status filter) |
| `POST` | `/api/registry/enrollments/{id}/approve` | **Different** supervisor approves (four-eyes) — writes `citizens_registry` |
| `POST` | `/api/registry/enrollments/{id}/reject` | Reject with `review_note` |
| `POST` | `/api/citizens/import` | HMAC-signed authority batch import (header `X-Import-Signature` = hex HMAC-SHA256 over raw body; sign with `scripts/sign_registry_import.py`) |
| `GET` | `/api/citizens/orphans` | List orphan biometric files |
| `POST` | `/api/citizens/orphans/cleanup` | Supervisor erases orphans |

### Iris

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/biometric/iris/enroll` | Enroll eye image for a citizen (`eye=left|right`, `provider=rgb|nir`) |
| `POST` | `/api/biometric/iris/verify` | Verify probe against stored template |
| `GET` | `/api/biometric/iris/template/{citizen_id}` | Returns `{template_exists, quality}` — never the template |

### Health & Misc

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | DB + face engine + watchlist + registry photo backend status |
| `GET` | `/health/face_engine` | `local_engine_status()` — `initialised`, `models_present`, `provider`, `last_error` (never downloads) |
| `GET` | `/{full_path}` | SPA fallback — must stay **last** (`/api/*` → 404 JSON, not HTML) |

**CORS** allowlist (`backend/app.py:275`): `localhost:5173`, `127.0.0.1:5173`, `localhost:8000`, `127.0.0.1:8000`, `sih-weld-psi.vercel.app`, `netraksha.xyz` (+ `www`/`api`), `web-production-6b7f1.up.railway.app` + `CORS_ORIGINS` extra. Unhandled 500s preserve CORS headers; `HTTPException` handler ensures 401/403 carry CORS.

---
