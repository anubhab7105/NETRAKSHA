# NETRAKSHA — AI-Based Fake Identity & Document Screening System

> **Smart India Hackathon (SIH2026) — Problem Statement 188**
> **Organization:** Ministry of Home Affairs (MHA) / Sashastra Seema Bal (SSB)
> **Domain:** Smart Automation · Homeland Security · Border Checkpoint Screening

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?logo=fastapi&logoColor=white)](backend/app.py)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](frontend/package.json)
[![Vite 8](https://img.shields.io/badge/Vite-8-646CFF?logo=vite&logoColor=white)](frontend/vite.config.js)
[![Tailwind 4](https://img.shields.io/badge/Tailwind-4-06B6D4?logo=tailwindcss&logoColor=white)](frontend/package.json)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](#license)

**One-liner:** A human-in-the-loop forensic screening workstation that checks a traveler's document, live face, and registry record across **15 isolated forensic modules** and presents an explainable **Green / Yellow / Red** verdict — the system flags risk, only an officer can deny entry.

---

## Table of Contents

- [1. Overview](#1-overview)
- [2. Feature Highlights](#2-feature-highlights)
- [3. Tech Stack](#3-tech-stack)
- [4. Repository Structure](#4-repository-structure)
- [5. Getting Started](#5-getting-started)
- [6. Documentation](#6-documentation)
- [7. License](#7-license)

---

## 1. Overview


At land border checkpoints, officers manually inspect passports, VISA, Aadhaar, PAN, Voter ID cards and the traveler's face to catch **forgeries, imposter substitution, and digitally altered documents**. Manual inspection is slow, subjective, and blind to modern physical and digital fabrication techniques (re-typeset MRZ, swapped portraits, print-scan recaptures, GAN faces, screen replay).

**NETRAKSHA** is an **AI-assisted, explainable screening workstation**:

- **Single-process FastAPI backend** (`backend/app.py:267`) serves all `/api/*` routes and the built React SPA.
- **Forensic pipeline** (`pipeline/`) runs **15 isolated modules** — every module returns the same `ModuleResult` contract (`pipeline/common.py:109`) and **never raises**; failures degrade to `status="inconclusive"` with `score=None`.
- **Hybrid face verification**: local **InsightFace `buffalo_l` (ArcFace, CPU)** is authoritative for the `match` boolean; **Gemini** adds cloud reasoning and OCR. Simulated Gemini scores **never force Red**.
- **Risk engine** (`pipeline/risk_engine.py:43`) aggregates all signals into a composite score and a hard-flag verdict (`Green < 0.35 < Yellow < 0.65 < Red`).
- **Human-in-the-loop + RBAC**: officers can only `clear`/`escalate`, supervisors decide `deny`, auditors are read-only. Every decision and automated check is written to a **hash-chained, append-only audit log**.

> **Core philosophy:** Every recommendation ships with per-module visual evidence (ELA heatmap, face side-by-side, physical-forgery zone overlay, liveness stats). No black-box score. No auto-deny.

---

## 2. Feature Highlights


| Capability | What it does |
|---|---|
| **6-layer document forensics** | OCR/MRZ + checksums + tamper (ELA + copy-move) + physical forgery (6 sub-checks) + deepfake (FFT) + quality gates |
| **3-way face verification** | `live ↔ doc` (primary) + `doc ↔ DB` + `live ↔ DB` via InsightFace local engine (`pipeline/face_match.py:449`) with quality-gated recapture prompts |
| **Active liveness** | MediaPipe `face_landmarker.task` (468-pt) fused blink (adaptive EAR) + motion + moiré + head-yaw/mouth-open challenges over a **14-frame / ~2.1 s burst** (`pipeline/liveness.py:450`) |
| **Iris (RGB prototype)** | Classical Hough + Gabor pipeline, pluggable `RGBProvider`/`NIRProvider` (`backend/biometric/iris/provider.py`), disclosed as *not NIR-grade* |
| **Registry & watchlist** | Fuzzy demographic reconciliation + trust-tier (`verified / legacy / unverified`) + `WatchlistProvider` with DB-backed or mocked mode |
| **Idempotent screening** | `Idempotency-Key: <uuid-v4>` required on `POST /api/screen` — exact-key replay, 409 in-flight guard, 10-min input-hash dedup (`backend/app.py:904`) |
| **Provenance & audit** | HMAC-signed provenance bundle per case + hash-chained `audit_log` with `prev_hash`/`entry_hash` (`backend/models.py:452`) + signed evidence URLs |
| **Governed registry** | Dual-approval (four-eyes, `approver ≠ requester`) + HMAC authority import (`scripts/sign_registry_import.py`) |
| **Resilient startup** | Self-healing columns (`ensure_model_columns/auth/registry_trust` — `backend/database.py:148`), sequence re-anchoring (`ensure_sequences`), background InsightFace prewarm |

---

## 3. Tech Stack


| Layer | Technology | Notes |
|---|---|---|
| **Backend** | FastAPI, Uvicorn, SQLAlchemy 2 (async), Pydantic 2 | Single-process; `sys.path` root injection (`backend/app.py:46`) |
| **Database** | Supabase PostgreSQL (`asyncpg`) · SQLite fallback in dev only | `DATABASE_URL` required in prod; self-healing migrations, no Alembic (`backend/database.py:18`) |
| **Auth** | `PyJWT`, `passlib[bcrypt]` (bcrypt-only), stdlib TOTP (RFC 6238), in-memory sliding-window rate limiter | `backend/auth_security.py:1` |
| **CV / Forensics** | OpenCV (`headless`), NumPy, Pillow, PassportEye, pytesseract, scikit-learn | System Tesseract required; no vendored binary |
| **Face** | InsightFace `buffalo_l` (ArcFace `w600k_r50` + `det_10g`), ONNX Runtime `CPUExecutionProvider` | ~300 MB, gitignored, background prewarm (`backend/app.py:458`) |
| **Liveness** | MediaPipe `face_landmarker.task` (468-pt, committed at `pipeline/vendor/models/face_landmarker.task`) | EAR + motion + FFT moiré + yaw/mouth |
| **Iris** | Classical Hough + polar unwrap + Gabor → 512-byte template, Hamming 0.32 (`pipeline/thresholds.json:12`) | `backend/biometric/iris/` |
| **AI Cloud** | `google-genai` SDK, cascade `gemini-flash-lite-latest → gemini-3.5-flash → gemini-3-flash-preview` (`pipeline/gemini_scanner.py:52`) + offline simulation (`is_simulated`) | Never Red-forcing in simulation |
| **Frontend** | React 19, Vite 8, Tailwind 4, React Router 7, Axios, lucide-react, `oxlint` | JS/JSX only, no TS (`frontend/package.json:1`) |
| **Infra** | Vercel (SPA + `/api` rewrite → Railway), Railway (FastAPI), Supabase (DB + Storage bucket `img`) | `vercel.json`, `railway.toml`, `Dockerfile` |

---

## 4. Repository Structure


```
.
├── backend/
│   ├── app.py                 # All /api routes, auth, idempotency, evidence signing, CORS, SPA fallback
│   ├── models.py              # 11 ORM tables (incl. iris_templates + screening_idempotency)
│   ├── database.py            # Engine (Postgres asyncpg / SQLite aiosqlite dev) + ensure_* self-heal
│   ├── seed.py                # Idempotent demo officers / citizens / watchlist + bootstrap admin (prod)
│   ├── auth_security.py       # JWT / TOTP / password policy / RateLimiter / secret gates
│   └── biometric/iris/        # RGB iris provider: detector, segmenter, normalizer, encoder, matcher, quality, liveness
├── pipeline/
│   ├── common.py              # ModuleResult contract, ok_result / inconclusive_result, evidence dir, image loaders
│   ├── thresholds.json        # Single source for all tuned thresholds (v1.0)
│   ├── ocr_mrz.py             # Tesseract --psm 6 + PassportEye + ICAO 9303
│   ├── checksums.py           # Verhoeff (Aadhaar-12), ICAO (7,3,1), PAN, EPIC dispatch
│   ├── demographic.py         # Token-sort Levenshtein (name ≥0.85, addr ≥0.60) + strict DOB/ID
│   ├── tamper.py              # ELA (JPEG q=90, JET overlay) + exact-duplicate SHA1 block-hash copy-move
│   ├── physical_forgery.py    # 6 sub-checks: layout / font / photo-boundary / print-scan / QR / security-features
│   ├── deepfake.py            # numpy.fft.fft2 radial spectrum heuristic (high_freq + peakedness + rolloff)
│   ├── face_match.py          # InsightFace buffalo_l local 1:1 + run_three_way_match (never raises)
│   ├── face_quality.py        # Capture & per-face gates (blur, brightness, pose, occupancy)
│   ├── document_quality.py    # Laplacian blur ≥50, brightness gate
│   ├── liveness.py            # MediaPipe EAR + motion + moiré + head-yaw/mouth-open challenges
│   ├── iris.py                # Pipeline facade over backend/biometric/iris providers
│   ├── gemini_scanner.py      # google-genai multi-image single call + cascading fallback + offline simulation
│   ├── watchlist.py           # WatchlistProvider / MockWatchlistProvider + DB loader
│   ├── risk_engine.py         # Rule-based composite Green/Yellow/Red + hard flags
│   ├── security_zones.py      # Legacy zone ROIs (still runs, superseded)
│   ├── fairness.py            # In-memory fairness ledger + GET /api/fairness/report
│   └── vendor/models/
│       └── face_landmarker.task  # Committed MediaPipe model (~ committed, not downloaded at runtime)
├── frontend/
│   ├── src/
│   │   ├── api.js             # Base-URL resolver + auth interceptors (401→/login, 403→/change-password)
│   │   ├── App.jsx            # Routes + SecurityGate + GovTopBar + code-split views
│   │   ├── views/             # Login · Dashboard · Scanner · CaseReport · AuditTrail · SecuritySetup · NotFound
│   │   └── components/        # Sidebar, SEO, Breadcrumbs, ui (GovNotice, WorkflowSteps, PageHeader), PersonBiometricCapture, IrisCapture
│   ├── vite.config.js         # /api proxy → :8000, SEO files (robots/sitemap/llms), sourcemap:false, chunk splitting
│   └── vercel.json            # SPA rewrites + cache headers (mirrored at repo root)
├── samples/
│   ├── genuine_doc.png        # Valid ICAO MRZ specimen (L898902C3 → Jasmine Specimen)
│   ├── tampered_doc.png       # Copy-move + splice specimen
│   ├── faces/                 # person_a / person_a_2 (match) / person_b (mismatch) + uploads/
│   ├── live/                  # blink_burst_*.png (12) / static_burst_*.png (8)
│   └── evidence/              # Runtime evidence PNGs (gitignored)
├── scripts/
│   ├── setup_vendor.sh        # Checks face_landmarker.task + system tesseract + buffalo_l pack (~300 MB)
│   └── sign_registry_import.py# HMAC-signs authority import batches (REGISTRY_IMPORT_SECRET)
├── tests/
│   ├── test_pipeline.py       # Checksums / demographic / watchlist / risk / Gemini / tamper<1.5s
│   ├── test_auth_security.py  # Password / TOTP / rate-limit / secret gates (isolated :memory: SQLite)
│   ├── test_face_quality.py   # Quality gates
│   ├── test_physical_forgery.py # Physical checks (<5 s)
│   └── test_three_way.py      # Local-authoritative 3-way + sim exclusion
├── docs/
│   └── iris_architecture.md   # RGB prototype vs NIR production path
├── vercel.json                # Root Vercel config (/api rewrite → Railway + SPA fallback)
├── railway.toml / Dockerfile  # Railway deploy
├── requirements.txt
├── .env.example               # Full env template (copy → .env, never commit .env)
└── README.md                  # This file
```

> `pipeline/__init__.py:1` exports all 15 modules. Do **not** inline module logic into routes — the contract and isolation guarantee depend on it.

---

## 5. Getting Started


### Prerequisites

| Requirement | Version / Notes |
|---|---|
| **Python** | 3.11+ (recommended via `uv`) |
| **Node.js** | 18+ and npm |
| **System Tesseract** | Windows: `winget install UB-Mannheim.TesseractOCR` · Debian: `sudo apt-get install -y tesseract-ocr tesseract-ocr-eng` — no vendored binary is shipped |
| **Gemini API Key** | Optional — without it the scanner runs **offline simulation** (`is_simulated=True`, `cloud_unavailable` banner, verdict floored at Yellow). Free key: https://aistudio.google.com/apikey (must start with `AIza`) |
| **Supabase PostgreSQL** | **Required in production** (`APP_ENV=production` fails fast without `DATABASE_URL`). In dev, absence falls back to local SQLite (`./local_dev.db` or `LOCAL_DB_PATH`) |

### 1. Clone & Environment

```powershell
# Clone
git clone https://github.com/soumyajit-cys/Python_Rule-Based-Fake-Identity-Document-Screening-System.git
cd Python_Rule-Based-Fake-Identity-Document-Screening-System

# .env — copy the template and fill at least DATABASE_URL + GEMINI_API_KEY
Copy-Item .env.example .env
# Edit .env — see §14 for the full key table
```

### 2. Python Backend

```powershell
# Create venv (PowerShell)
uv venv --python 3.11 .venv
.venv\Scripts\Activate.ps1

# Install deps
uv pip install -r requirements.txt

# Verify runtime assets (face_landmarker.task + tesseract + buffalo_l pack)
bash scripts/setup_vendor.sh
# - face_landmarker.task is committed; re-downloads if missing
# - reports system tesseract + tessdata (without it OCR → inconclusive)
# - buffalo_l (~300 MB, gitignored) is provisioned via InsightFace; without it
#   registry face legs report N/A with local_face_engine_unavailable
```

### 3. Run Backend

```powershell
# From repo root — auto-runs init_db + self-healing + seed_all() on startup
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
# → http://127.0.0.1:8000/health
# → http://127.0.0.1:8000/docs  (Swagger, when enabled)
```

Demo logins (non-production only, all `must_change_password=True` — you will be routed to `/change-password` on first login):

| Username | Password | Role | Unit |
|---|---|---|---|
| `officer1` | `Officer@123` | officer | `BORDER_UNIT_1` |
| `supervisor1` | `Supervisor@123` | supervisor | `BORDER_UNIT_1` |
| `auditor1` | `Auditor@123` | auditor | `HQ` |
| `officer2` | `Officer@123` | officer | `BORDER_UNIT_2` |

Production creates **only** the bootstrap supervisor from `BOOTSTRAP_ADMIN_USER`/`PASS`/`UNIT` (strong password enforced, `must_change_password=True`).

### 4. Frontend

```powershell
cd frontend
npm install
npm run dev      # Vite on http://localhost:5173 — proxies /api → 127.0.0.1:8000
npm run lint     # oxlint
npm run build    # → frontend/dist — served by FastAPI via SPA fallback in prod
```

### 5. Tests

```powershell
# All suites
python -m pytest tests/ -v

# Focused
python -m pytest tests/test_pipeline.py::TestRiskEngine -v
python -m pytest tests/test_auth_security.py -v
python -m pytest tests/test_three_way.py -v
python -m pytest tests/test_physical_forgery.py -v
```

Performance assertions: **tamper < 1.5 s**, **physical_forgery < 5 s** (CPU).

---

## 14. Configuration — Environment Variables

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

## 15. Testing

```powershell
python -m pytest tests/ -v
```

| Suite | Covers | Key asserts |
|---|---|---|
| `tests/test_pipeline.py` | Checksums (Verhoeff/PAN/EPIC/ICAO), demographic (fuzzy/DoB), watchlist, risk engine (Green→Red escalation), Gemini offline simulation, tamper speed | Tamper **< 1.5 s** on both `genuine_doc.png` and `tampered_doc.png` |
| `tests/test_auth_security.py` | Password policy, TOTP (`totp_at`/`verify_totp`/`match_window`), `RateLimiter`, `secret_error`, `is_production` | Isolated `:memory:` SQLite engines — never touches the app DB |
| `tests/test_face_quality.py` | Capture/face quality gates | Blur/brightness/pose thresholds |
| `tests/test_physical_forgery.py` | 6 sub-checks (layout/font/frame/moiré/QR/guilloche) | **< 5 s** end-to-end |
| `tests/test_three_way.py` | `run_three_way_match` completeness + simulated-exclusion | Only `evidence=="local"` registry mismatches force Red |

The default `GEMINI_API_KEY=""` in `.env.example` is intentional — tests assert `is_simulated=True` and that simulated scores never force Red. CPU-only; InsightFace uses `CPUExecutionProvider`; sub-2.5 s end-to-end (sequential OCR + 3× local face + Gemini) is aspirational.

---

## 16. Deployment

| Layer | Host | Config |
|---|---|---|
| **Frontend (SPA)** | **Vercel** | `vercel.json:7` — `installCommand`/`buildCommand`/`outputDirectory: frontend/dist`; `rewrites: /api/(.*) → https://web-production-ab06a.up.railway.app/api/$1` + SPA fallback `/(?!assets|api) → /index.html`; cache headers for `assets/*` (1 y immutable) + `robots/sitemap/llms` (1 d) + security headers (`nosniff`, `DENY`, `camera=(self)`) |
| **Backend (FastAPI)** | **Railway** | `railway.toml` / `Dockerfile` / `Procfile` — `python -m uvicorn backend.app:app --host 0.0.0.0 --port $PORT`; `SCREEN_EVIDENCE_DIR` on persistent volume; `DATABASE_URL` (pooler `:6543`) + `SUPABASE_*` + `JWT_SECRET` + `BOOTSTRAP_ADMIN_*` from Railway secrets |
| **Database + Storage** | **Supabase** | Postgres (pooler) + Storage bucket `img` (private). Connection string from Dashboard → Project Settings → Database → Connection string |

**Frontend `VITE_SITE_URL`** (`frontend/vite.config.js:8`) is the single source for `robots.txt`/`sitemap.xml`/`llms.txt` + `%SITE_URL%` in `index.html`. Override via Vercel env when switching domains.

**CORS** — the Vercel `/api` rewrite avoids cross-origin entirely for `netraksha.xyz`; the backend allowlist still covers direct Railway/preview access.

---

## 17. Demo Scenarios

Specimen `samples/genuine_doc.png` / `samples/tampered_doc.png` (ICAO MRZ `L898902C3`) map to the seeded citizen **Jasmine Specimen** (`passport L898902C3`, `1969-12-04`) so the flagship demos hit a DB record.

| # | Scenario | Inputs | Expected |
|---|---|---|---|
| 1 | **Clean clearance** | Genuine doc + matching live (`person_a` vs `person_a_2`) + matching DB + no watchlist | **Green** — all local checks clear, no hard flags |
| 2 | **Demographic forgery** | Altered DOB/Name vs `citizens_registry` | **Red / Yellow** — field discrepancy table highlights altered field; Green forbidden |
| 3 | **Physical tampering** | `tampered_doc.png` (copy-move/splice) | **Red / Yellow** — ELA overlay + physical-forgery zones fire |
| 4 | **Identity imposter** | Live face ≠ doc/DB (local InsightFace, sim excluded) | **Red** — `FACE_MISMATCH` or `DOC_DB_FACE_MISMATCH`/`LIVE_DB_FACE_MISMATCH` |
| 5 | **Watchlist hit** | Name/ID matching `watchlist_entries` (e.g. `Vikram Singh Chauhan`) | **Red (HIGH RISK)** — `WATCHLIST_HIT`, `is_mocked=True` (violet badge) |
| 6 | **Liveness spoof** | Static burst (`static_burst_*.png`) or screen replay | **≥ Yellow** — `LIVENESS_FAILURE` / `screen_replay` |
| 7 | **Iris mismatch** | Wrong eye / poor quality | **Red / Yellow** — `IRIS_MISMATCH` / `IRIS_QUALITY_POOR` |

---

## 18. Known Gaps & Limitations

Preserved honestly — do not claim these as done until implemented:

- **Violet `MOCKED DATA` badge** and **Aadhaar `XXXX-XXXX-1234` masking** are spec'd but **unimplemented** (the badge currently renders as `HIT`/`CLEAR` chips + `is_mocked` notice).
- `VITE_SITE_URL` has a triple-default (`vite.config.js` / `vercel.json` / docs) — not yet single-sourced.
- `og-image` extension mismatch and `public/%SITE_URL%` placeholder are open bugs.
- `EvidenceImage` component hardcodes `/api` instead of `api.defaults.baseURL`.
- `handleVerify` is duplicated in two views.
- **CPU-only** — no GPU; InsightFace `CPUExecutionProvider` is correct but slower than the aspirational sub-2.5 s target.
- **Iris** is RGB-only (see §12) — do not present as NIR-grade.
- Evidence on ephemeral disks is wiped on restart unless `SCREEN_EVIDENCE_DIR` points at a persistent volume.

---

## 19. License

MIT — see `LICENSE` (add one if missing). This project was built for SIH 2026 Problem Statement 26188 (MHA/SSB). Synthetic samples only — no real PII is shipped.

---

<p align="center">
  <strong>NETRAKSHA — See. Verify. Secure.</strong><br/>
  <sub>Sashastra Seema Bal · Ministry of Home Affairs · Government of India</sub><br/>
  <sub>Built for SIH 2026 · SIXTH SENSE01</sub>
</p>

