# AGENTS.md

## Stack & layout
- Single-process FastAPI backend: `backend/app.py` (all `/api/*` routes + SPA fallback), `backend/database.py` (Supabase-PostgreSQL-only, fail-fast + `ensure_*` self-heal), `backend/models.py` (10 tables), `backend/seed.py` (idempotent), `backend/auth_security.py` (JWT/TOTP/password/throttles).
- Forensic pipeline: `pipeline/` — `ocr_mrz`, `checksums`, `demographic`, `tamper` (ELA + exact-hash copy-move), `physical_forgery`, `deepfake` (FFT), `face_match` (InsightFace `buffalo_l` local-authoritative), `face_quality` + `document_quality` (gates), `liveness` (MediaPipe EAR/motion/moiré), `gemini_scanner` (`google-genai`, `gemini-3.6-flash` + simulated fallback), `watchlist` (`WatchlistProvider`), `risk_engine`, `security_zones` (legacy), `fairness`; contract in `pipeline/common.py` (`ModuleResult`, `ok_result`/`inconclusive_result`); thresholds in `pipeline/thresholds.json`. Never inline module logic into routes. Note: `__init__.py` exports only 10 of 15 modules.
- Frontend: `frontend/` React 19 + Vite 8 + Tailwind 4 (**JS/JSX only, no TS**), axios + react-router 7, lint = `oxlint`. Views: `Login/Dashboard/Scanner/CaseReport/AuditTrail/SecuritySetup`; client `src/api.js`.
- DB: Supabase-PostgreSQL-only — `DATABASE_URL` required (`postgresql+asyncpg://`, `postgresql://` auto-rewritten); missing/SQLite URL raises at import. No Alembic. (`aiosqlite` remains in requirements test-only for isolated `:memory:` fixtures in `test_auth_security.py`; never used at runtime.)

## Commands
- Setup (PowerShell): `uv venv --python 3.11 .venv; .venv\Scripts\Activate.ps1; uv pip install -r requirements.txt`
- Env: copy `.env.example` → `.env`. Never commit `.env` / `*.db`. Full keys: `GEMINI_API_KEY/MODEL`, `APP_ENV/JWT_SECRET(≥32 prod)/JWT_EXPIRY_HOURS/MFA_TOKEN_MINUTES`, `LOGIN|MFA_RATE_LIMIT_*`, `BOOTSTRAP_ADMIN_USER/PASS/UNIT` (prod only), `REGISTRY_IMPORT_SECRET`, `DATABASE_URL/DB_ECHO/POOL_SIZE/MAX_OVERFLOW`, `SCREEN_EVIDENCE_DIR`.
- Backend (repo root): `python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000` (`app.py` inserts root into `sys.path`; auto `init_db` + `seed_all()`).
- Frontend (in `frontend/`): `npm install` / `npm run dev` (proxy `/api`→`127.0.0.1:8000`) / `npm run build` (→`dist`, served by FastAPI) / `npm run lint` (`oxlint`).
- Assets: `bash scripts/setup_vendor.sh` (checks committed `face_landmarker.task` + system Tesseract — no vendored binary). System Tesseract required (`winget`/`apt`); without it OCR → inconclusive.
- Tests: `python -m pytest tests/ -v`; focused: `test_pipeline.py::TestRiskEngine`, `test_auth_security.py`, `test_face_quality.py`, `test_physical_forgery.py`, `test_three_way.py`. Asserts: tamper <1.5s, physical <5s.
- Seed logins (non-prod only, all `must_change_password=True`): `officer1/Officer@123`, `supervisor1/Supervisor@123`, `auditor1/Auditor@123` (+`officer2/BORDER_UNIT_2`).

## Env & startup gotchas
- `GEMINI_API_KEY` empty → `scan_document` returns `is_simulated=True`; simulated face/tamper never force Red (tests rely on this). Default model `gemini-3.6-flash` (not 1.5/2.0).
- `APP_ENV=production` raises on default/short `JWT_SECRET` and on missing `BOOTSTRAP_ADMIN_*`; never creates demo users. `REGISTRY_IMPORT_SECRET` falls back to `JWT_SECRET` with warning.
- Naive datetimes only: `_utcnow_naive()` for DB writes. Aware `datetime.now(timezone.utc)` 500s on Postgres via asyncpg.
- Startup self-heals (`ensure_model_columns/auth/registry_trust/sequences`); don't write migrations. Postgres explicit-ID legacy DBs re-anchor via `setval(max(id)+1)`.
- Evidence: `SCREEN_EVIDENCE_DIR` or `samples/evidence/` (blank=unset; gitignored). No public mount — `GET /evidence/*` is 404; use signed `/api/evidence/token|view|{filename}` (`expires_in` 30–3600s).
- Registry photos (`citizens_registry.photo_uri`): local paths AND `http(s)` Supabase signed URLs — `_resolve_db_photo()` downloads remote ones once into `$TMPDIR/netraksha_registry_photos` (8s timeout, 5MB cap, magic-byte check) and feeds them to Gemini Image 3 + local 3-way. Failures degrade to `partial` with specific `db_pairs_unavailable_reason` (`no_registry_photo|registry_photo_missing_on_server|registry_photo_download_failed`), never halt.
- CPU-only (no GPU); InsightFace uses `CPUExecutionProvider`. Sub-2.5s end-to-end is aspirational (sequential OCR + 3× local face + Gemini).
- Local face engine (InsightFace `buffalo_l`, ~300MB, gitignored): prewarmed in a background task at startup (loud `[startup]` log), status in `/health.face_engine` (`local_engine_status()` never downloads), provision via `scripts/setup_vendor.sh`. Dead engine → registry legs N/A with `local_face_engine_unavailable`, or a narrow late-Gemini 3-image fallback (`_needs_late_gemini_face`, real-cloud only, sourced `gemini_late`, never Red-forcing).

## Pipeline contracts (Rules.md / Techspec §5 — non-negotiable)
- `ModuleResult(module_name, score, status, raw_output, evidence_uri)` via `ok_result` (clipped 0–1) / `inconclusive_result` (`score=None` + `reason[:200]`). `status` only `ok|inconclusive`. Never raise — degrade (evidence-write failures swallowed; physical isolates per-check).
- Any `inconclusive` → verdict ≥ Yellow. Hard flags (`risk_engine.py`): demographic-critical / local face (incl. `evidence==local` DB pairs) / watchlist → Red; unverified trust / demo-unavailable / recapture → ≥Yellow; liveness fail / deepfake ≥0.7 → ≥Yellow. Thresholds: face 0.55 (band 0.45–0.65), tamper 0.4/0.7, deepfake 0.7, liveness 0.45, name 0.85/addr 0.60.
- Tamper = ELA + SHA1 exact-duplicate blocks (not ORB/NCC — fix stale comments if touched). Keep <1.5s; run local CV concurrent with Gemini via `run_in_executor` + `asyncio.gather`.
- Watchlist (`is_mocked=True`) + simulated Gemini (`is_mocked=is_simulated`) drive DEMO notices; registry trust is separate (`verified/legacy/unverified`). Route lookups via `WatchlistProvider`; registry writes only via dual-approval/HMAC import.
- Human-in-the-loop + RBAC: officers own-cases + never `deny`; supervisors unit-scoped + enroll/approve (four-eyes, approver≠requester); auditors read-only (cases/audit). Override needs `reason≥3` + `version`/`If-Match`; decided → 409.
- Gaps to preserve (don't claim done): violet `MOCKED DATA` badge and Aadhaar `XXXX-XXXX-1234` masking are spec'd but unimplemented; `SITE_URL` triple-default + `og-image` ext + `public/%SITE_URL%` + `EvidenceImage` hardcoded `/api` + duplicated `handleVerify` are open bugs.

## API quirks
- Auth: `POST /api/auth/login` → session JWT (`purpose=session`, `jti`=session_id) or `mfa_token` (`purpose=mfa`, 5 min). `GET/POST` bare aliases exist (`/auth/login`, `/screen`, `/cases`, `/audit`) but canonical is `/api/*`. 403s route to `/change-password` (`PASSWORD_CHANGE_REQUIRED` / `MFA_SETUP_REQUIRED`); 401 (non-step-up) wipes `localStorage` → `/login`. Passwords = bcrypt-only; unknown users dummy-verified; policy ≥10 chars, 3/4 classes.
- `POST /api/screen` multipart (`document_image*`, `live_capture?`, `live_frames[]?`) requires `Idempotency-Key` (header or `idempotency_key` form): `^[A-Za-z0-9\-_:.]{8,128}$`, UUID v4. Same key+session+input → replay `deduplicated:true`; same key+different → 422; in-flight → 409; same input+different key (10 min) → replay `duplicate_of_key`. Frontend mints per-intent UUID, regenerates on input change.
- Frontend `api.js`: `DEV` or `:8000` → same-origin `/api`; else `VITE_API_BASE_URL` (must end `/api`). `VITE_SITE_URL` drives `vite.config.js` SEO files (only `index.html` gets `%SITE_URL%` replaced). Don't hardcode `localhost:8000`; fix `EvidenceImage` to use `api.defaults.baseURL`.
- CORS allowlist in `app.py` (5173/8000 + vercel + netraksha domains); unhandled 500s preserve CORS headers. SPA fallback `/{full_path}` must stay last (`api/*` → 404 JSON). `sourcemap:false` intentional.
