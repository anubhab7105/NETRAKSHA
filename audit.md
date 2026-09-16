# Netraksha — Full Production-Readiness Audit

> **Audit Date:** 2026-09-15 | **Auditor:** Antigravity AI  
> **Scope:** Complete codebase — backend, pipeline, frontend, infra, tests, scripts, assets  
> **Directive:** Evidence-based audit only. No code changes made.

---

## 1. Project Inventory / Runtime Graph

### Repository Layout

| Path | Purpose | LOC / Size |
|---|---|---|
| `backend/app.py` | Single FastAPI process — all `/api/*` routes + SPA fallback | 4,934 lines / 234KB |
| `backend/database.py` | Engine, session, `init_db`, 4 `ensure_*` self-heal migrations | 375 lines |
| `backend/auth_security.py` | JWT, TOTP, bcrypt, rate limiter | 231 lines |
| `backend/models.py` | 10 SQLAlchemy ORM tables | 542 lines |
| `backend/seed.py` | Idempotent seeder — officers, citizens, watchlist | 291 lines |
| `backend/biometric/iris/` | Full iris biometric sub-module (8 files) | ~1,500 lines |
| `pipeline/__init__.py` | Exports all 15 pipeline modules | 54 lines |
| `pipeline/common.py` | `ModuleResult`, contract helpers, `EVIDENCE_DIR`, image loader | 253 lines |
| `pipeline/risk_engine.py` | Pure `assess_risk()` function, all hard-flag rules | 408 lines |
| `pipeline/gemini_scanner.py` | Gemini API call + simulated fallback | 435 lines |
| `pipeline/face_match.py` | InsightFace buffalo_l 3-way match, `prewarm_local_engine` | 567 lines |
| `pipeline/liveness.py` | MediaPipe EAR/motion/moiré burst analysis | 609 lines |
| `pipeline/physical_forgery.py` | 6-check deterministic physical forgery detector | 797 lines |
| `pipeline/tamper.py` | ELA + SHA-1 exact-block copy-move | ~400 lines |
| `pipeline/ocr_mrz.py` | Tesseract OCR + ICAO 9303 MRZ + check-digit validation | 22KB |
| `pipeline/deepfake.py` | FFT-based deepfake/replay detection | ~12KB |
| `pipeline/checksums.py` | Document number validation (Luhn/Aadhaar/PAN/MRZ) | ~6KB |
| `pipeline/demographic.py` | Name/DOB/address fuzzy comparison | ~8KB |
| `pipeline/watchlist.py` | `WatchlistProvider` — DB + mock lookup | ~5KB |
| `pipeline/security_zones.py` | Legacy zone/layout/QR overlay checker | 156 lines |
| `pipeline/fairness.py` | In-memory fairness logger | ~5KB |
| `pipeline/iris.py` | Thin facade → `backend/biometric/iris/provider` | 27 lines |
| `frontend/` | React 19 + Vite 8 + Tailwind 4, 6 views, 6 components | ~3,000 lines JSX/JS |
| `tests/` | 10 pytest files | ~2,500 lines |
| `scripts/` | `setup_vendor.sh`, `sign_registry_import.py` | 2 files |
| `samples/` | Specimen docs, faces, burst frames, evidence PNGs | ~62MB committed |
| `pipeline/vendor/` | `face_landmarker.task` (1.4MB committed), buffalo_l models (ignored) | ~342MB locally |
| `render.yaml` | Render.com deployment (free tier) | 78 lines |

### Runtime Architecture (Single Process)

```
Browser → FastAPI (uvicorn, 1 process)
            ├── /api/auth/* (JWT, MFA, bcrypt)
            ├── /api/screen (POST) ─── asyncio.gather():
            │     ├── run_tamper()           [ThreadPool]
            │     ├── run_physical_forgery() [ThreadPool]
            │     ├── run_deepfake()         [ThreadPool]
            │     ├── run_liveness()         [ThreadPool]
            │     ├── scan_document()        [ThreadPool → Gemini API]
            │     ├── run_three_way_match()  [ThreadPool → InsightFace ONNX]
            │     └── run_security_zones()   [ThreadPool, optional]
            ├── /api/cases, /api/audit, /api/citizens, /api/evidence, /api/health
            └── /{full_path:path}  (React SPA fallback)
```

**Key runtime facts:**
- No separate worker processes, message queues, or scheduled jobs
- Rate limiters stored in-memory per process — do not survive multi-worker deployments
- InsightFace buffalo_l prewarmed in a background `asyncio.create_task()` at startup
- Supabase PostgreSQL (asyncpg) in production; SQLite + aiosqlite in dev only (never at runtime on Render)
- Evidence PNGs written to `SCREEN_EVIDENCE_DIR` or `samples/evidence/` (ephemeral on Render `/tmp/evidence`)

---

## 2. Production-Readiness Verdict

> **Overall Verdict: C+ — Demo-Quality, Not Production-Ready**

Strong security primitives exist (bcrypt, HMAC provenance, RBAC, idempotency, TOTP MFA, dual-approval registry). However, multiple **production blockers** remain: no token revocation, rate limiters broken under any multi-worker deployment, a committed dev database with hashed credentials, 629MB of binary model artifacts partly committed (ZIP + extracted), no CI/CD, no structured logging, no graceful shutdown, and known open UI bugs documented in AGENTS.md itself.

---

## 3. RAM / CPU Resource Audit

### Memory Footprint

| Component | RAM (approx.) | Notes |
|---|---|---|
| FastAPI + Python runtime | ~80MB | Baseline |
| InsightFace buffalo_l (ONNX) | ~340–500MB | `w600k_r50.onnx`=174MB, `1k3d68.onnx`=143MB loaded into ONNX runtime session |
| MediaPipe FaceLandmarker | ~60MB | `face_landmarker.task` (1.4MB file, larger loaded) |
| OpenCV + NumPy | ~50MB | Shared |
| Gemini SDK (`google-genai`) | ~20MB | Import cost |
| DB connection pool (asyncpg, 5 conns) | ~5–10MB | |
| **Total (face engine ON)** | **~600–700MB** | Exceeds Render free tier (512MB) |
| **Total (DISABLE_LOCAL_FACE_ENGINE=true)** | **~200–250MB** | Fits Render free tier |

> [!CAUTION]
> On the Render free tier (512MB RAM), `DISABLE_LOCAL_FACE_ENGINE=true` **MUST** be set or the instance will OOM-crash on startup. The `render.yaml` does set this correctly, but it means all face matching degrades to Gemini-only — a significant capability reduction that is not prominently documented for operators.

### CPU Bottlenecks

| Operation | Estimated Latency | Issue |
|---|---|---|
| `subprocess(git rev-parse HEAD)` on every `/api/screen` request | 20–100ms | Spawns a child process per screening — unnecessary |
| `run_physical_forgery()` | 1–5s (spec says <5s) | Largest module (797 lines, 6 sub-checks) |
| `run_three_way_match()` (InsightFace) | 1–3s (CPU-only ONNX) | Sequential face crops + 3 cosine distances |
| `scan_document()` (Gemini API) | 1.5–3s | Network round-trip |
| Total end-to-end | **3–8s** | Well above the "sub-2.5s aspiration" in AGENTS.md |

### Disk Usage

| Asset | Size | Can Delete? |
|---|---|---|
| `pipeline/vendor/models/models/buffalo_l.zip` | 288MB | **YES** — Redundant archive; extracted folder already present |
| `pipeline/vendor/models/models/buffalo_l/` (extracted) | ~341MB | No — required for InsightFace (but gitignored, not in repo) |
| `samples/evidence/` | ~51MB | **YES from repo** — Test output, gitignored in .gitignore but committed |
| `samples/live/` | ~10MB | Borderline — test burst data; low value in repo |
| `local_dev.db` | 159KB | **YES** — Should never be committed |

> [!WARNING]
> **`local_dev.db` is committed to the repo** (appears in git history). The `.gitignore` has `*.db` but this file was committed before that rule was added or with `--force`. It likely contains bcrypt-hashed passwords for seed accounts. While bcrypt makes cracking hard, committing a database with any credential data is a security and compliance violation.

> [!WARNING]
> **`samples/evidence/` is listed in `.gitignore` but those 51MB of PNG files appear present in the repository.** Either they were committed before the gitignore rule, or with `--force`. These are test-run forensics images containing specimen document crops — a PII risk if the repo is public.

---

## 4. Dependency Audit

### `requirements.txt` Analysis

```
fastapi==0.115.12
uvicorn[standard]==0.34.2
sqlalchemy[asyncio]==2.0.36
asyncpg==0.30.0
aiosqlite==0.21.0         ← RUNTIME DEV/TEST ONLY (used for :memory: in tests)
passlib[bcrypt]==1.7.4
pyjwt[crypto]==2.10.1
python-multipart==0.0.20
python-dotenv==1.1.0
google-genai==1.18.0
insightface==0.7.3
onnxruntime==1.21.0
mediapipe==0.10.21
opencv-python==4.11.0.86
numpy==2.1.3
Pillow==11.2.0
pytesseract==0.3.13
pyotp==2.9.0
pytest==8.3.5             ← TEST-ONLY, should not be in prod requirements
pyzbar==0.1.2
```

| Issue | Severity |
|---|---|
| `pytest` in production requirements | Low — wastes CI install time, slight attack surface |
| `aiosqlite` in production requirements | Low — only used in test fixtures with `:memory:`, but gets installed in prod |
| `insightface==0.7.3` pinned | Medium — no minor-patch updates; known CVEs in older versions |
| `onnxruntime==1.21.0` pinned | Medium — CPU-only, no GPU; must match models |
| No `requirements-dev.txt` split | Low — standard practice not followed |

---

## 5. File and Asset Cleanup Report

### Files That Should Be Removed / Excluded

| File/Path | Reason | Safe to Delete? |
|---|---|---|
| `local_dev.db` | Committed dev SQLite database with seeded bcrypt-hashed credentials | **YES** — add to .gitignore and remove from history |
| `pipeline/vendor/models/models/buffalo_l.zip` | 288MB redundant ZIP; extracted folder already present | **YES** — remove ZIP, keep extracted |
| `samples/evidence/*.png` (~63 files) | Test run artifacts (51MB), should be gitignored; some may contain specimen doc images | **YES from repo** — already in .gitignore, need git rm |
| `package-lock.json` (root, 133 bytes) | Appears to be a nearly-empty stray file — root has no `package.json` | **YES** — spurious file |
| `samples/live/` | 20 burst PNGs (~10MB), only needed for running tests | Borderline — keep in repo for test reproducibility OR move to LFS |

### Files to Verify / Scrutinize

| File | Concern |
|---|---|
| `docs/` directory | Not reviewed — may contain architecture/threat docs; check for embedded secrets |
| `backend/biometric/iris/` | 8 modules, full prototype implementation — never wire-tested at border scale; prototype-grade code in production critical path |
| `vercel.json` (root + `frontend/vercel.json`) | Not reviewed — may contain outdated rewrites or exposed API keys |

---

## 6. Configuration Audit

### Environment Variables

| Variable | Default | Production Risk |
|---|---|---|
| `JWT_SECRET` | `sih-hackathon-dev-secret-change-in-prod` | **CRITICAL if not overridden** — startup enforces ≥32 chars in production only |
| `APP_ENV` | `development` | Must be `production` on Render — `render.yaml` sets this correctly |
| `DATABASE_URL` | Not set | **CRITICAL** — missing → SQLite fallback (forbidden in production by code) |
| `GEMINI_API_KEY` | Empty | No key → simulated fallback, every case is "DEMO ONLY" |
| `REGISTRY_IMPORT_SECRET` | Falls back to `JWT_SECRET` | Warning logged at startup; operators may miss it |
| `BOOTSTRAP_ADMIN_USER/PASS` | Empty | Required in production — startup refuses if missing |
| `SCREEN_EVIDENCE_DIR` | `samples/evidence/` | On Render, set to `/tmp/evidence` — ephemeral, wiped on restart |
| `DISABLE_LOCAL_FACE_ENGINE` | Not set | Must be `true` on Render free tier (512MB limit) |
| `SUPABASE_*` | Not set | Required for registry photo resolution from Supabase Storage |

> [!IMPORTANT]
> `render.yaml` correctly sets `APP_ENV=production`, `DATABASE_URL` (via Render env var), and `DISABLE_LOCAL_FACE_ENGINE=true`. However, `GEMINI_API_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, and the bootstrap credentials must be set manually in the Render dashboard — there is no documentation or startup check reminding operators.

### Hardcoded Values (Security Concern)

| Location | Hardcoded Value | Risk |
|---|---|---|
| `backend/app.py` CORS list | `https://sih-weld-psi.vercel.app` | Hackathon-era staging domain in production CORS allowlist |
| `frontend/src/api.js:31` | `sih-weld-psi.vercel.app` → `api.netraksha.xyz` | Hackathon domain triggers production API redirect |
| `backend/app.py` audit log line 2904 | `os.environ.get("JWT_SECRET", "sih-hackathon-dev-secret-change-in-prod")` | Default dev secret embedded in audit verification logic (different path from startup check) |
| `backend/auth_security.py` | Default secret check | Well-handled in startup; the audit endpoint duplicates it less safely |

---

## 7. Security Audit

### CRITICAL Issues

#### SEC-1: No JWT Token Revocation
**Evidence:** `backend/auth_security.py` — `_create_token()` issues JWTs with a `jti` claim, but no revocation list is maintained. `backend/app.py` `_auth()` decodes and validates the JWT without checking if the `jti` was invalidated. Logout (`/api/auth/logout`) only writes an audit log entry.

**Impact:** A stolen token remains valid until its expiry (`JWT_EXPIRY_HOURS`, default 8h). An officer who is terminated or whose credentials are compromised has no way to be immediately invalidated without changing the `JWT_SECRET` (which invalidates all sessions).

**Severity:** HIGH for a border security system.

---

#### SEC-2: Rate Limiters Are Per-Process (Broken Under Multi-Worker)
**Evidence:** `backend/auth_security.py` — `RateLimiter` uses `threading.Lock()` + a Python dict. This state is not shared across OS processes. If deployed with `--workers 2` (uvicorn), each worker has its own independent `RateLimiter`. An attacker can make 5 attempts per worker = effectively 10 attempts (N workers × 5).

**Impact:** Brute-force throttling on login, MFA, and password change silently fails under multi-worker deployment. `render.yaml` currently uses 1 worker (safe), but this is a latent defect.

**Severity:** HIGH (latent, depends on deployment config).

---

#### SEC-3: Base64 Fallback Token (Trivially Forgeable)
**Evidence:** `backend/app.py` lines around `_HAS_PYJWT`:
```python
if not _HAS_PYJWT:
    # unsigned base64 token — any attacker can forge officer claims
```
The `_verify_token()` function has a corresponding unsigned decode path. If PyJWT is somehow not installed (e.g., broken venv), all sessions become forgeable.

**Impact:** If `pyjwt` is missing, the entire authentication system collapses silently. No startup warning is emitted for this condition.

**Severity:** HIGH (probability is low given requirements.txt, but catastrophic if triggered).

---

#### SEC-4: `local_dev.db` Committed to Repository
**Evidence:** File `local_dev.db` (159KB) exists at repo root. It is a SQLite database likely containing seed officers (bcrypt-hashed), seeded citizens (real-ish identity data), and watchlist entries.

**Impact:** If the repo is or ever becomes public, the database exposes bcrypt-hashed passwords (rainbow-table resistant but computationally attackable with GPUs), seeded document numbers, seeded citizen addresses, and a full schema dump.

**Severity:** HIGH — requires git history rewrite to fully remediate.

---

#### SEC-5: `collect_provenance()` Calls `subprocess(git)` Per Request
**Evidence:** `backend/app.py` — `collect_provenance()` is called on every `/api/screen` request and contains:
```python
subprocess.check_output(["git", "rev-parse", "HEAD"])
```
**Impact:** (a) Command injection if git is not properly found; (b) 20–100ms latency added per screening request; (c) If git is absent (e.g., in a Docker container without git), it throws an exception (caught gracefully, but noisy); (d) The git hash is stable per deployment — it could be cached at startup.

**Severity:** MEDIUM.

---

#### SEC-6: Iris "Encryption" Is Not Encryption
**Evidence:** `backend/app.py` `_encrypt_template()`:
```python
# Simple envelope: base64(template) + HMAC; in production use Fernet/AES-GCM
sig = hmac.new(_JWT_SECRET.encode(), data, hashlib.sha256).hexdigest()[:16]
return f"{sig}:{b64}"
```
This is HMAC-prefixed base64, not encryption. The template is readable by anyone with database access. The code itself says "in production use Fernet/AES-GCM."

**Impact:** Iris biometric templates stored in the database are readable in plaintext to anyone with DB access. For a biometric database, this is a serious privacy violation.

**Severity:** MEDIUM-HIGH (biometric data must be encrypted at rest, not merely integrity-checked).

---

#### SEC-7: Hardcoded Hackathon Domain in CORS and API Client
**Evidence:**
- `backend/app.py` CORS origins: includes `https://sih-weld-psi.vercel.app`
- `frontend/src/api.js:31`: hostname check for `sih-weld-psi.vercel.app` routes to production API

**Impact:** The old hackathon Vercel deployment, if anyone still controls that domain, can make authenticated cross-origin requests to the production API.

**Severity:** MEDIUM.

---

### MEDIUM Issues

| ID | Issue | Location |
|---|---|---|
| SEC-8 | No `Content-Security-Policy` header on API responses | `app.py` exception handlers — CORS headers only |
| SEC-9 | `X-Request-ID` in response body but not in headers | `app.py` — should be in both for log correlation |
| SEC-10 | Audit log chain uses `JWT_SECRET` for HMAC — rotating the secret breaks chain verification | `app.py:2904` |
| SEC-11 | `REGISTRY_IMPORT_SECRET` falls back to `JWT_SECRET` — single secret protects two distinct operations | `app.py:3019-3023` |
| SEC-12 | MFA TOTP secret (`totp_secret`) stored as plaintext text column | `models.py:56` — should be encrypted at rest |
| SEC-13 | Evidence token `_verify_evidence_token()` has an unsigned fallback path (same `_HAS_PYJWT` issue) | `app.py:4776-4783` |
| SEC-14 | `officer2` is hardcoded in seed with password `Officer@123` — not overridable via env | `seed.py:55` |

---

## 8. Reliability / Failure Modes

### Startup Failure Modes

| Condition | Behavior |
|---|---|
| Missing `DATABASE_URL` in production | `database.py` raises `RuntimeError` at import — **correct fail-fast** |
| Weak `JWT_SECRET` in production | `auth_security.py` raises at import — **correct fail-fast** |
| Missing `BOOTSTRAP_ADMIN_*` in production | `seed.py` raises `RuntimeError` during startup — **correct fail-fast** |
| Missing `buffalo_l` models | `prewarm_local_engine()` logs loudly but does NOT crash — graceful degradation |
| Missing Tesseract binary | OCR returns `inconclusive_result` — graceful degradation |
| Missing `face_landmarker.task` | Liveness + security_zones return `inconclusive_result` — graceful degradation |

### Runtime Failure Modes

| Scenario | Behavior | Issue? |
|---|---|---|
| Gemini API timeout / outage | `cloud_unavailable=True`, verdict floored at Yellow | OK |
| InsightFace OOM crash | `_three_way_job()` catches all exceptions, returns empty pairs | OK |
| DB write failure during screening | Raises 500 (the `async with session` commit is uncaught) | **Medium** — case data lost, no retry |
| Evidence dir full | `new_evidence_path()` creates path but `cv2.imwrite()` silently fails | Low — swallowed |
| Concurrent duplicate screening | Idempotency key + DB constraint handles this correctly | OK |
| Session expiry during long screening | JWT validated at start; 8h default is long enough for single screening | OK |
| `git rev-parse HEAD` fails (git absent) | Exception caught in `collect_provenance()`, continues | OK |
| Supabase connection pool exhausted | asyncpg raises — no retry logic, 500 to user | Medium |

### No Graceful Shutdown
**Evidence:** `backend/app.py` has `@app.on_event("startup")` but **no `@app.on_event("shutdown")`**. The InsightFace ONNX session, MediaPipe FaceLandmarker, and database connection pool are never explicitly torn down on SIGTERM. On Render, the process receives SIGTERM on deploys — asyncpg connections may leak.

---

## 9. Performance Audit

### Per-Request Bottlenecks

| Bottleneck | Impact | Source |
|---|---|---|
| `subprocess(["git", "rev-parse", "HEAD"])` per screening | +20–100ms | `app.py collect_provenance()` |
| InsightFace 3-way match (CPU ONNX) | +1–3s | `face_match.py run_three_way_match()` |
| `run_physical_forgery()` — 6 sub-checks | +1–5s | `physical_forgery.py` |
| Gemini API round-trip | +1.5–3s | `gemini_scanner.py` |
| Registry photo download (first hit) | +0–8s | `_resolve_db_photo()` from Supabase Storage |
| Late Gemini fallback (optional second Gemini call) | +1.5–3s | `_needs_late_gemini_face()` path |

**End-to-end estimate (face engine enabled, Gemini live, DB hit with photo):** ~5–12 seconds.

The parallel `asyncio.gather()` design is correct, but the bottleneck is the thread pool executing CPU-bound tasks sequentially within each worker. Physical forgery and InsightFace share the same thread pool — they don't actually parallelize on a single-core free-tier instance.

### No Caching
- No HTTP caching headers for static SPA assets (the `FileResponse` SPA fallback does not set `Cache-Control` or `ETag`)
- The git hash in `collect_provenance()` is computed on every request (could be cached at startup)
- No Redis / APM / response caching

### DB Query Inefficiencies

| Query | Issue |
|---|---|
| `_citizen_identity_clause()` uses `func.upper(func.replace(func.replace(...)))` on every lookup | No functional index on normalized number — full table scan on large registries |
| `_check_evidence_access()` does `evidence_uri.contains(safe_name)` | `LIKE '%filename%'` — full scan of `module_results` table |
| `list_audit()` loads all matching rows into memory before pagination | `select(AuditLog).limit(limit).offset(offset)` is correct, but with no index on `timestamp` + actor, large audit tables will be slow |

---

## 10. Observability

### Current State

| Concern | Status |
|---|---|
| Structured logging | ❌ None — uses `print()` throughout (`single_log` is a `print` wrapper) |
| Log correlation | ❌ No request ID in headers (only in response body) |
| Metrics | ❌ None — no Prometheus, no OpenTelemetry, no `/metrics` endpoint |
| Tracing | ❌ None |
| Error tracking | ❌ None (no Sentry, no Rollbar) |
| Health check | ✅ `GET /health` returns DB type, face engine status, registry photo backend |
| Audit log | ✅ Append-only HMAC chain in DB — covers officer actions |
| Evidence images | ✅ PNG overlays per module per case |
| Provenance | ✅ HMAC-signed provenance JSON per case |

### What's Missing for Production Observability
- `uvicorn` access logs are the only HTTP-level log — no application-level timing or error rates
- No alerting on error rates, OOM, or latency spikes
- No dashboard / APM for Render free tier

---

## 11. Testing

### Test Coverage Summary

| Test File | What It Tests | Issues |
|---|---|---|
| `test_pipeline.py` | 6 scenario tests + module contracts (OCR, tamper, face, liveness) | Solid; includes timing assertion <1.5s for tamper |
| `test_auth_security.py` | JWT, TOTP, rate limiter, password policy (uses SQLite `:memory:`) | Good isolation |
| `test_face_quality.py` | Face quality gate, recapture signals | Exists |
| `test_physical_forgery.py` | Physical forgery 6 sub-checks | Exists |
| `test_three_way.py` | 3-way InsightFace match | Exists |
| Other test files | Additional coverage | Not fully reviewed |

### Testing Gaps

| Gap | Severity |
|---|---|
| No integration test for `/api/screen` end-to-end HTTP request | High — the most complex route has no HTTP-level test |
| No test for multi-worker rate limiter failure (known bug) | High |
| No test for JWT token revocation (it doesn't exist) | Medium |
| No CI/CD pipeline (no GitHub Actions) | High — tests only run manually |
| `test_pipeline.py:assert_contract()` hardcodes allowed module names (line 45-47) — doesn't include `physical_forgery`, `checksums`, `liveness` etc. | Low |
| No load / performance test | Medium |

---

## 12. Deployment Review

### Render.com Configuration (`render.yaml`)

**Strengths:**
- `APP_ENV=production` correctly set
- `DISABLE_LOCAL_FACE_ENGINE=true` saves memory on free tier
- `DB_POOL_SIZE=2`, `DB_MAX_OVERFLOW=5` — appropriate for free-tier Supabase (limited connections)
- `buildCommand: bash build.sh` runs `pip install` + vendor setup + frontend build
- `startCommand: python -m uvicorn backend.app:app --host 0.0.0.0 --port $PORT`

**Weaknesses:**
- Free tier: 512MB RAM — face engine disabled, evidence disk is ephemeral
- **No `--workers` flag** — single worker process. Correct for in-memory rate limiters, but no request concurrency beyond asyncio
- No health check path configured in `render.yaml` — Render uses HTTP health checks but no `healthCheckPath` field seen
- No environment variable validation at build time

### No CI/CD
No GitHub Actions, GitLab CI, CircleCI, or any other CI configuration was found. Tests run manually only.

### Vercel Split-Deploy (Optional)
- `vercel.json` at root and in `frontend/` were not fully reviewed
- `frontend/src/api.js:31` has hardcoded `sih-weld-psi.vercel.app` hostname → redirects to `api.netraksha.xyz`
- `VITE_API_BASE_URL` must be set in Vercel environment for split-deploy to work correctly

---

## 13. "What Can I Delete?" Report

### Immediately Safe to Delete (No Functionality Lost)

| Item | Size | Evidence of Safety |
|---|---|---|
| `pipeline/vendor/models/models/buffalo_l.zip` | 288MB | Extracted folder present; `setup_vendor.sh` downloads the ZIP on fresh install; the extracted folder is what the code uses |
| `local_dev.db` | 159KB | SQLite dev artifact; runtime uses PostgreSQL; `.gitignore` already has `*.db` |
| Root `package-lock.json` (133 bytes) | 133B | No `package.json` at root; stray file from incorrect working directory during `npm install` |
| `samples/evidence/*.png` (63 files) | ~51MB | Already in `.gitignore`; test artifacts; CI should generate them, not commit them |

### Should Be Moved to Dev Dependencies Only

| Item | Reason |
|---|---|
| `pytest==8.3.5` in `requirements.txt` | Test runner; should be in `requirements-dev.txt` |
| `aiosqlite==0.21.0` in `requirements.txt` | Only used in test fixtures; no runtime usage |

### Legacy / Low-Value Code (Review Before Removing)

| Item | Notes |
|---|---|
| `pipeline/security_zones.py` | Labeled "legacy" in AGENTS.md and `__init__.py` docstring. Output is gathered in `asyncio.gather()` but the result (`security_result`) is **never passed to `assess_risk()`** — it runs but its score does not affect the verdict. Costs CPU per screening with zero risk impact. |
| `pipeline/iris.py` (facade) | Thin 27-line wrapper to `backend/biometric/iris/provider`. Only used by `app.py` iris enrollment routes. If iris enrollment is not deployed, this entire subsystem is dead weight. |
| `backend/biometric/iris/` (8 files, ~1,500 lines) | Full iris biometric implementation — prototype-grade, never tested at production scale. The verify route (`/api/biometric/iris/verify`) exists but is not surfaced in the frontend. |
| `DEMO_MODE` env var | The `_DEMO_MODE` flag is read but functionally unused — demo behavior comes from `GEMINI_API_KEY` being empty. `_DEMO_MODE` only gates whether a simulated result is classified `ok` vs `inconclusive` in module persistence (line 2306). |

---

## 14. Production Blockers

> [!CAUTION]
> The following issues MUST be resolved before deploying to a real border security context.

| # | Blocker | Severity | Evidence |
|---|---|---|---|
| P1 | **No JWT revocation** — stolen tokens remain valid until expiry | CRITICAL | `app.py _auth()`, `auth_security.py _create_token()` |
| P2 | **`local_dev.db` in repo** — dev database with credential data committed | CRITICAL | File present at repo root, 159KB |
| P3 | **Rate limiters broken under multi-worker** — brute-force throttling silently bypassed | CRITICAL | `auth_security.py RateLimiter` in-memory dict |
| P4 | **Iris biometric "encryption" is base64** — templates readable in DB plaintext | HIGH | `app.py _encrypt_template()` |
| P5 | **No CI/CD** — no automated tests on push/PR | HIGH | No CI config found |
| P6 | **`samples/evidence/` committed** — forensic test images in repo (potential PII) | HIGH | 63 PNGs, 51MB |
| P7 | **No graceful shutdown** — ONNX/MediaPipe/asyncpg not torn down on SIGTERM | MEDIUM | No `@app.on_event("shutdown")` |
| P8 | **`collect_provenance()` spawns `git` subprocess per request** | MEDIUM | `app.py collect_provenance()` |
| P9 | **Hackathon CORS + API client domain** left in production code | MEDIUM | `app.py` CORS, `api.js:31` |
| P10 | **No structured logging** — `print()` only; impossible to search/alert on errors | MEDIUM | All pipeline modules + app.py |
| P11 | **`security_zones.py` runs per screening but score is never used by risk engine** | LOW | `app.py:1583-1625`, `risk_engine.py` |
| P12 | **Open UI bugs documented but unimplemented** (MOCKED DATA badge, Aadhaar masking, EvidenceImage hardcoded `/api`) | LOW | AGENTS.md "Gaps to preserve" |

---

## 15. Final Scorecard

| Category | Score (0–10) | Notes |
|---|---|---|
| **Security** | 5/10 | RBAC, bcrypt, TOTP, HMAC provenance ✅; no revocation, insecure iris storage, dev DB committed ❌ |
| **Reliability** | 5/10 | Graceful pipeline degradation ✅; no graceful shutdown, no retries on DB commit ❌ |
| **Performance** | 4/10 | Parallel gather ✅; git subprocess per request, no caching, 5–12s end-to-end ❌ |
| **Observability** | 2/10 | Health endpoint, HMAC audit trail ✅; no structured logging, no metrics, no tracing ❌ |
| **Testing** | 4/10 | Pipeline unit tests, auth tests ✅; no HTTP integration tests, no CI/CD ❌ |
| **Deployment** | 5/10 | Render config mostly correct ✅; no CI, ephemeral evidence, OOM risk ❌ |
| **Code Quality** | 6/10 | Pipeline contracts clean, good RBAC, idempotency ✅; 4934-line `app.py`, stale AGENTS.md comment ❌ |
| **Data Integrity** | 6/10 | HMAC provenance, dual-approval registry ✅; dev DB committed, no Alembic ❌ |
| **Dependency Health** | 5/10 | Pinned versions ✅; no dev/prod split, pytest in prod, known-old insightface ❌ |
| **Frontend** | 5/10 | Good API client, CORS proxy ✅; hardcoded domains, open bugs documented ❌ |
| **Overall** | **4.7 / 10** | Demo-quality for a hackathon; real border deployment requires P1–P6 resolved |

---

## TOP 10 Recommended Actions

> **Priority order — fix P1–P6 before any production deployment.**

### 1. 🔴 Implement JWT Revocation (P1)
Cache issued `jti` values in Redis or a DB table. On logout, insert the `jti`. In `_auth()`, reject tokens whose `jti` appears in the revocation store. Alternatively, use short-lived tokens (15–30min) with refresh token rotation.

### 2. 🔴 Remove `local_dev.db` from Repository (P2)
```bash
git filter-branch --force --index-filter 'git rm --cached --ignore-unmatch local_dev.db' HEAD
```
Then add `*.db` and `local_dev.db` explicitly to `.gitignore`. Rotate the seeded test passwords.

### 3. 🔴 Fix Rate Limiter for Multi-Worker Safety (P3)
Replace in-memory `RateLimiter` with a Redis-backed implementation (e.g., `redis-py` with sliding window). This also unlocks horizontal scaling without breaking throttles.

### 4. 🔴 Encrypt Iris Templates with AES-256-GCM (P4)
Replace `_encrypt_template()` with Fernet (from `cryptography` package, already available transitively). Generate a dedicated `IRIS_ENCRYPTION_KEY` env var (separate from `JWT_SECRET`).

### 5. 🔴 Add CI/CD with GitHub Actions (P5)
Create `.github/workflows/ci.yml` that runs `pytest tests/ -v` on every push and PR. Block merges on test failures. Add `npm run lint` for the frontend.

### 6. 🔴 Remove Committed Evidence Images (P6)
```bash
git rm -r --cached samples/evidence/
```
Ensure `.gitignore` entries for `samples/evidence/` and `tests/evidence/` are respected.

### 7. 🟡 Cache Git Hash at Startup; Eliminate Subprocess Per Request (P8)
In `startup()`, call `subprocess.check_output(["git", "rev-parse", "HEAD"])` once and store the result in a module-level variable. `collect_provenance()` reads it from memory.

### 8. 🟡 Remove Hackathon Domains from CORS and API Client (P9)
Remove `sih-weld-psi.vercel.app` from the CORS allowlist in `app.py`. Remove the hardcoded hostname check in `frontend/src/api.js:31`. Add a `CORS_ORIGINS` env var (already supported) for legitimate deploy domains.

### 9. 🟡 Add Structured Logging (P10)
Replace all `print()` calls with Python `logging` (or `structlog`). Emit JSON-formatted log entries with `request_id`, `officer_id`, `case_id`, `module_name`, `duration_ms`. This is the minimum needed for production incident response.

### 10. 🟡 Remove or Wire `security_zones.py` (P11)
Either: (a) pass `security_result` to `assess_risk()` and update `risk_engine.py` to use it; or (b) remove `run_security_zones()` from the parallel gather entirely (saves ~100–500ms per screening with zero verdict impact). Current state: runs, wastes CPU, result discarded.

---

## Appendix: Known Open Bugs (From AGENTS.md)

These are bugs the team documented but left unimplemented. They do not block security functionality but will confuse end users:

- Violet `MOCKED DATA` badge — specified but not rendered in frontend
- Aadhaar number `XXXX-XXXX-1234` masking — specified but not implemented
- `EvidenceImage` component hardcodes `/api` instead of using `api.defaults.baseURL`
- `SITE_URL` triple-default in `vite.config.js` (default → env → default chain)
- Duplicate `handleVerify` function in Scanner view
- `og-image` extension and `public/%SITE_URL%` token not substituted
