# Configuration, Testing & Deployment

## Configuration — Environment Variables


Copy `.env.example` → `.env`. **Never commit `.env` or `*.db`.**

| Variable | Default | Required in prod? | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | *(empty)* | No (demo works without) | Google AI key (`AIza…`). Empty/invalid → `is_simulated=True` + Yellow floor. |
| `GEMINI_MODELS` | `gemini-flash-lite-latest,gemini-3.5-flash,gemini-3-flash-preview` | No | Comma-separated cascade — scanner tries in order, 10 s timeout per model (`pipeline/gemini_scanner.py:62`). |
| `GEMINI_MODEL` | *(falls back to cascade)* | No | Legacy single-model override (still respected; `GEMINI_MODELS` takes priority). |
| `APP_ENV` | `development` | **Yes** | `development`/`staging`/`production`. `production` enforces secret strength + bootstrap admin, never seeds demo users. |
| `JWT_SECRET` | `sih-hackathon-dev-secret-change-in-prod` | **Yes (≥ 32 chars)** | HMAC secret for JWT + audit chain + evidence + provenance signatures. `secret_error` fail-fast in prod. Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `JWT_EXPIRY_HOURS` | `8` | No | Session JWT lifetime |
| `MFA_TOKEN_MINUTES` | `5` | No | MFA step-up token lifetime |
| `LOGIN_RATE_LIMIT_MAX_ATTEMPTS` / `WINDOW_SECONDS` | `5` / `300` | No | Login brute-force throttle |
| `MFA_RATE_LIMIT_MAX_ATTEMPTS` / `WINDOW_SECONDS` | `5` / `300` | No | TOTP code throttle |
| `BOOTSTRAP_ADMIN_USER` / `PASS` / `UNIT` | *(empty)* | **Yes in prod** | Initial supervisor (only account created in prod, `must_change_password=True`, strong password enforced) |
| `REGISTRY_IMPORT_SECRET` | *(falls back to `JWT_SECRET`)* | **Yes (dedicated)** | HMAC secret for authority import batches (`scripts/sign_registry_import.py`). Fallback logs warning. |
| `DATABASE_URL` | *(empty → local SQLite in dev)* | **Yes in prod** | Supabase Postgres: `postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:6543/postgres` (port **6543** pooler on Render). `postgresql://` auto-rewritten to `postgresql+asyncpg://`. |
| `DB_ECHO` | `false` | No | SQLAlchemy echo |
| `DB_POOL_SIZE` / `MAX_OVERFLOW` | `5` / `10` | No | Pool sizing (Render free-tier pin `2`/`5` in `render.yaml`) |
| `SCREEN_EVIDENCE_DIR` | `samples/evidence/` | No | Evidence PNG dir (blank = unset). Mount a persistent disk here on Render/Railway. No public mount — use signed `/api/evidence/*`. |
| `CORS_ORIGINS` | *(stock allowlist)* | No | Extra comma-separated origins (stock: `5173`/`8000`/`vercel`/`netraksha`/`railway`) |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` / `SUPABASE_ANON_KEY` | *(empty)* | For Storage photo refs | Registry `photo_uri` as Storage path `img/<object>` (bucket `img`). Private reads need `SERVICE_ROLE_KEY` (60 s signed URL, `SUPABASE_PHOTO_SIGNED_TTL` 15–600). Never put service key in frontend env. |
| `SUPABASE_PHOTOS_BUCKET` | `img` | No | Storage bucket name |
| `WATCHLIST_USE_DB` | *(auto: Postgres→DB, SQLite→mock)* | No | `false` to force mock; `true` to force DB |
| `WATCHLIST_MOCKED` | `false` | No | `true` keeps `is_mocked=True` even on DB data (violet badge) |
| `DISABLE_LOCAL_FACE_ENGINE` | *(empty)* | No | `1`/`true` to skip InsightFace prewarm (e.g. 512 MB free tier) — registry legs become N/A with narrow late-Gemini fallback |
| `VITE_API_BASE_URL` | *(empty → same-origin `/api`)* | No (frontend) | Absolute backend URL ending `/api` (e.g. `https://api.netraksha.xyz/api`). Ignored on `netraksha.xyz`/`vercel`/`railway` hosts (forced same-origin). |
| `VITE_SITE_URL` | `https://netraksha.xyz` | No (frontend) | Canonical origin for SEO files (`robots.txt`/`sitemap.xml`/`llms.txt` + `%SITE_URL%` in `index.html`) |

Naive datetimes only: use `_utcnow_naive()` (`backend/app.py:100`) for DB writes — `datetime.now(timezone.utc)` 500s on Postgres via `asyncpg`.

---

## Testing


```powershell
python -m pytest tests/ -v
```

| Suite | Covers | Key asserts |
|---|---|---|
| `tests/test_pipeline.py` | Checksums (Verhoeff/PAN/EPIC/ICAO), demographic (fuzzy/DoB), watchlist, risk engine (Green→Red escalation + boundary floors), Gemini offline simulation, tamper speed (median-of-3, flaky-tolerant) | Tamper **< 1.5 s** median on both `genuine_doc.png` and `tampered_doc.png` |
| `tests/test_api_contracts.py` | `/screen` idempotency matrix, RBAC override matrix, `/audit/verify` chain, HMAC import, evidence bounds + `/evidence/*` 404, masking, boundaries, document_quality/fairness/Gemini-parse/OCR-no-Tesseract | Isolated `:memory:` SQLite; heavy pipeline mocked |
| `tests/test_auth_security.py` | Password policy, TOTP (`totp_at`/`verify_totp`/`match_window`), `RateLimiter`, `secret_error`, `is_production` | Isolated `:memory:` SQLite engines — never touches the app DB |
| `tests/test_face_quality.py` | Capture/face quality gates | Blur/brightness/pose thresholds |
| `tests/test_physical_forgery.py` | 6 sub-checks (layout/font/frame/moiré/QR/guilloche) | **< 5 s** median-of-3 end-to-end |
| `tests/test_three_way.py` | `run_three_way_match` completeness + simulated-exclusion (engine legs skip without `buffalo_l`) | Only `evidence=="local"` registry mismatches force Red |
| `tests/test_liveness_challenge.py` | Liveness challenges + bursts | Blink `live`, static not-live |
| `tests/test_security_zones.py` | Legacy zone ROIs | Score bounds + shape |
| `tests/test_iris.py` | RGB prototype (experimental uncalibrated thresholds 0.28/0.32/0.36) | Prototype placeholder, not production-grade |

The default `GEMINI_API_KEY=""` in `.env.example` is intentional — tests assert `is_simulated=True` and that simulated scores never force Red. CPU-only; InsightFace uses `CPUExecutionProvider`; sub-2.5 s end-to-end (sequential OCR + 3× local face + Gemini) is aspirational.

---

## Deployment


| Layer | Host | Config |
|---|---|---|
| **Frontend (SPA)** | **Vercel** | `vercel.json:7` — `installCommand`/`buildCommand`/`outputDirectory: frontend/dist`; `rewrites: /api/(.*) → https://web-production-6b7f1.up.railway.app/api/$1` + SPA fallback `/(?!assets|api) → /index.html`; cache headers for `assets/*` (1 y immutable) + `robots/sitemap/llms` (1 d) + security headers (`nosniff`, `DENY`, `camera=(self)`) |
| **Backend (FastAPI)** | **Railway** | `railway.toml` / `Dockerfile` / `Procfile` — `python -m uvicorn backend.app:app --host 0.0.0.0 --port $PORT`; `SCREEN_EVIDENCE_DIR` on persistent volume; `DATABASE_URL` (pooler `:6543`) + `SUPABASE_*` + `JWT_SECRET` + `BOOTSTRAP_ADMIN_*` from Railway secrets |
| **Database + Storage** | **Supabase** | Postgres (pooler) + Storage bucket `img` (private). Connection string from Dashboard → Project Settings → Database → Connection string |

**Frontend `VITE_SITE_URL`** (`frontend/vite.config.js:8`) is the single source for `robots.txt`/`sitemap.xml`/`llms.txt` + `%SITE_URL%` in `index.html`. Override via Vercel env when switching domains.

**CORS** — the Vercel `/api` rewrite avoids cross-origin entirely for `netraksha.xyz`; the backend allowlist still covers direct Railway/preview access.

---

## Demo Scenarios


Specimen `samples/genuine_doc.png` / `samples/tampered_doc.png` (ICAO MRZ `L898902C3`) map to the seeded citizen **Jasmine Specimen** (`passport L898902C3`, `1969-12-04`) so the flagship demos hit a DB record.

| # | Scenario | Inputs | Expected |
|---|---|---|---|
| 1 | **Clean clearance** | Genuine doc + matching live (`person_a` vs `person_a_2`) + matching DB + no watchlist | **Green** — all local checks clear, no hard flags |
| 2 | **Demographic forgery** | Altered DOB/Name vs `citizens_registry` | **Red / Yellow** — field discrepancy table highlights altered field; Green forbidden |
| 3 | **Physical tampering** | `tampered_doc.png` (copy-move/splice) | **Red / Yellow** — ELA overlay + physical-forgery zones fire |
| 4 | **Identity imposter** | Live face ≠ doc/DB (local InsightFace, sim excluded) | **Red** — `FACE_MISMATCH` or `DOC_DB_FACE_MISMATCH`/`LIVE_DB_FACE_MISMATCH` |
| 5 | **Watchlist hit** | Name/ID matching `watchlist_entries` (e.g. `Arjun Veer Rathore`) | **Red (HIGH RISK)** — `WATCHLIST_HIT`, `is_mocked=True` (violet badge) |
| 6 | **Liveness spoof** | Static burst (`static_burst_*.png`) or screen replay | **≥ Yellow** — `LIVENESS_FAILURE` / `screen_replay` |
| 7 | **Iris mismatch** | Wrong eye / poor quality | **Red / Yellow** — `IRIS_MISMATCH` / `IRIS_QUALITY_POOR` |

---
