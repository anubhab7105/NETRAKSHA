# Python Rule-Based Fake Identity & Document Screening System

**Smart India Hackathon (SIH) — Problem Statement 26188**  
**Organization:** Ministry of Home Affairs (MHA) / Sashastra Seema Bal (SSB)  
**Domain:** Smart Automation / Homeland Security / Border Checkpoint Screening  

---

## 1. Overview

At border checkpoints, immigration and security officers manually inspect passports, visas, and traveler faces to detect forgeries, imposter substitution, and altered documents. This manual process is slow, subjective, and prone to missing sophisticated physical and digital fabrications.

This system provides an **AI-assisted forensic screening tool** that evaluates travel credentials and biometric identity in real time across forensic layers, presenting explainable visual evidence and a composite risk rating (Green / Yellow / Red) to the officer.

### Core Philosophy: Human-in-the-Loop
- **The system only flags risk; only a human officer can deny entry.**
- Every recommendation is accompanied by per-module explainable evidence rather than a black-box score.
- All assessments and human overrides are written to an append-only, hash-chained audit trail.

---

## 2. System Architecture

```
                                   [ SCREENING KIOSK ]
                             (React 19 + Vite + Tailwind 4, JS/JSX)
                                      │              │
                     1. Document Image (webcam)    2. Live Face Burst (14 frames, ~2.1s)
                                      │              │
                                      ▼              ▼
                               ┌─────────────────────────────┐
                               │       FastAPI Gateway       │
                               │   (Single-Process Engine)   │
                               └──────────────┬──────────────┘
                                              │
               ┌──────────────────────────────┴──────────────────────────────┐
               │                  FORENSIC SCREENING PIPELINE                │
               ▼                                                             ▼
┌──────────────────────────────┐                              ┌──────────────────────────────┐
│  1. OCR & Checksums          │                              │  5. Hybrid Face Match        │
│  Tesseract + PassportEye     │                              │  InsightFace buffalo_l LOCAL │
│  Verhoeff / ICAO / PAN/EPIC  │                              │  (authoritative) + Gemini    │
│  + Gemini classifier/OCR     │                              │  cloud (reasoning)           │
└──────────────┬───────────────┘                              │  • Live vs Doc / Doc vs DB   │
               │                                              │  • Live vs DB                │
┌──────────────▼───────────────┐                              └──────────────┬───────────────┘
│  2. Demographic Cross-Check  │                                             │
│  `citizens_registry` Table   │                              ┌──────────────▼───────────────┐
│  • Name (fuzzy ≥0.85) & DOB  │                              │  6. Liveness Check           │
│  • Address / ID parity       │                              │  MediaPipe FaceLandmarker    │
└──────────────┬───────────────┘                              │  • EAR + motion + moiré      │
               │                                              │  • blink/head_turn/mouth     │
               │                                              │  • IRIS Scan                 │
┌──────────────▼───────────────┐                              └──────────────┬───────────────┘
│  3. Tamper + Physical Checks │                                             │
│  • ELA + exact-duplicate     │                              ┌──────────────▼───────────────┐
│    copy-move (SHA1 blocks)   │                              │  7. Watchlist / Lookout DB   │
│  • MRZ-font / photo-frame /  │                              │  Mocked registry via         │
│    moiré / QR (physical)     │                              │  `WatchlistProvider`         │
└──────────────┬───────────────┘                              │  • `is_mocked=True`          │
               │                                              └──────────────┬───────────────┘
┌──────────────▼───────────────┐                                             │
│  4. Deepfake (FFT) + Quality │                                             │
│  • Radial spectrum heuristic │                                             │
│  • doc/face quality gates    │                                             │
└──────────────┬───────────────┘                                             │
               └──────────────────────────────┬──────────────────────────────┘
                                              │
                                              ▼
                               ┌─────────────────────────────┐
                               │         RISK ENGINE         │
                               │   Rule-Based Composite Flag │
                               │   (Green / Yellow / Red)    │
                               └──────────────┬──────────────┘
                                              │
                                      ┌───────┴───────┐
                                      ▼               ▼
                        [ OFFICER DASHBOARD ]   [ IMMUTABLE AUDIT LOG ]
                        • Visual Evidence Cards • Hash-chained ledger
                        • Demographic Parity    • Officer Override History
                        • 3-Way Face Verdicts   • Provenance signatures
```

Flow: sequential local OCR pre-pass (for registry lookup) → parallel `asyncio` local CV (tamper, physical_forgery, deepfake, liveness, local 3-way) + Gemini cloud call → demographic reconciliation → risk engine. See `Techspec.md` §1.

---

## 3. Forensic Screening Modules

| # | Module | Technology / Engine | Detection Objective |
|---|---|---|---|
| **1** | **OCR & Demographic Extraction** | Tesseract (`pytesseract --psm 6`) + PassportEye MRZ + regex + Gemini `gemini-3.6-flash` classifier (`google-genai` SDK) | Full Name, DOB, Document Number, Address/Father's Name, ICAO 9303 checksums. Offline `is_simulated=True` fallback when `GEMINI_API_KEY` unset. |
| **2** | **Checksums** | Pure Python: Verhoeff (Aadhaar-12), ICAO (7,3,1) (Passport), `[A-Z]{5}[0-9]{4}[A-Z]` (PAN), `[A-Z]{3}[0-9]{7}` (EPIC) | Eliminates AI digit hallucination. |
| **3** | **Database Cross-Verification** | Token-sort Levenshtein (name ≥0.85, addr ≥0.60) + strict DOB/ID | Cross-references `citizens_registry`. Critical fields: Full Name, DOB, Document Number. |
| **4** | **Tamper Detection** | ELA (JPEG q=90 residual, JET overlay) + exact-duplicate SHA1 block-hash copy-move | Splicing + copy-move duplicates. Evidence: `tamper_<id>.png`. Must complete <1.5s (tested). |
| **5** | **Physical Forgery** | OpenCV/Numpy + QR detector: layout, MRZ-font lattice, photo-frame quad, print-scan moiré, QR, guilloche/hologram inventory | Re-typeset MRZ, swapped photo, print-scan counterfeits ELA misses. |
| **6** | **Deepfake Detection** | `numpy.fft.fft2` radial spectrum (`high_freq + peakedness + rolloff`), no pretrained CNN | GAN upsampling artifacts. `method=fft_frequency_artifact_heuristic`. |
| **7** | **Face Verification (hybrid)** | **Local authoritative:** InsightFace `buffalo_l` (ArcFace, cosine, threshold 0.55, CPU fallback) for all pairs with both inputs; **Cloud:** Gemini 3-way reasoning; simulated cloud scores are excluded from verdict | Live vs Doc (primary), Doc vs DB, Live vs DB. Only `evidence==local` registry mismatches force Red. |
| **8** | **Liveness Detection** | MediaPipe `face_landmarker.task` (468-pt EAR) + inter-frame motion + FFT moiré + head-yaw/mouth-open; challenges `blink/head_turn/mouth_open`; `MIN_BURST=3`, `LIVE_THRESHOLD=0.45` | 14-frame burst; defeats photo/screen replay. |
| **9** | **Watchlist Lookup** | `WatchlistProvider` / `MockWatchlistProvider` (5 fictional entries) | `is_hit`, `is_mocked=True`. Violet badge is spec'd but not yet rendered — see Tracker gap. |
| — | Quality / fairness / zones (supporting) | `document_quality` (Laplacian blur ≥50, brightness), `face_quality` gates, `security_zones` legacy ROIs, `fairness` in-memory ledger | Gates and `GET /api/fairness/report`; not standalone verdicts. |

Thresholds: `pipeline/thresholds.json` (`face_match 0.55` band 0.45–0.65, `tamper 0.4/0.7`, `deepfake 0.7`, `liveness 0.45`).

---

## 4. Key Architectural Decisions

1. **Hybrid face verification (local-authoritative):**
   - InsightFace `buffalo_l` runs locally (CPU `CPUExecutionProvider` — no GPU on dev box) and decides all match booleans.
   - Gemini (`google-genai` SDK, default `GEMINI_MODEL=gemini-3.6-flash`) adds classification, OCR, and biometric reasoning. Offline simulation (`is_simulated=True`) keeps demos/tests working without a key; simulated scores never force Red.
2. **Supabase PostgreSQL only (10 tables, no local fallback):**
   - `officers`, `citizens_registry`, `registry_enrollments`, `screening_cases`, `extracted_fields`, `module_results`, `officer_actions`, `audit_log`, `screening_idempotency`, `watchlist_entries` (see `Schema.md`).
   - `DATABASE_URL` is **required** (`postgresql+asyncpg://`, `postgresql://` auto-rewritten); the backend refuses to start without it. Schema self-heals at startup (`ensure_*`); no Alembic.
3. **Fault Isolation Guarantee:**
   - Every `run_*` catches all errors → `status="inconclusive"`, `score=None`. Any inconclusive forces verdict ≥ Yellow. `POST /api/screen` never 500s on module failure.
4. **Auth & governance built in:**
   - bcrypt (passlib only) + JWT (`purpose=session`, 8h) + supervisor TOTP step-up + forced rotation + 5/300s rate limits + unit scoping (`BORDER_UNIT_1/2`, `HQ`).
   - `POST /api/screen` requires `Idempotency-Key` (UUID v4). Controlled registry enrollment (dual-approval four-eyes + HMAC authority import), hash-chained audit (`GET /api/audit/verify`), signed provenance, authenticated evidence URLs.

---

## 5. Repository Structure

```text
├── Appflow.md                 # Screen-by-screen application flow
├── Design.md                  # UI/UX spec (JS/React, current gaps flagged)
├── Implementationplan.md      # Sprint plan (completed — see Tracker)
├── PRD.md                     # Product Requirements Document (SIH 26188)
├── Rules.md                   # System non-negotiables and coding guardrails
├── Schema.md                  # Database schema (10 tables)
├── Techspec.md                # Technical spec & API contracts
├── Tracker.md                 # Build status & open gaps
├── AGENTS.md                  # Agent working notes
├── backend/                   # FastAPI single-process API
│   ├── app.py                 # All routes, auth, idempotency, evidence, startup
│   ├── models.py              # 10 ORM tables
│   ├── database.py            # Dual engine + self-healing migrations
│   ├── seed.py                # Demo officers/citizens/watchlist (idempotent)
│   └── auth_security.py       # JWT/MFA/password/rate-limit primitives
├── pipeline/                  # Forensic modules (never inline into routes)
│   ├── common.py              # ModuleResult contract, evidence dir, image loaders
│   ├── thresholds.json        # All tuned thresholds (single source)
│   ├── ocr_mrz.py             # Tesseract + PassportEye + ICAO
│   ├── checksums.py           # Verhoeff / ICAO / PAN / EPIC
│   ├── demographic.py         # Fuzzy reconciliation
│   ├── tamper.py              # ELA + exact-duplicate copy-move
│   ├── physical_forgery.py    # Layout/font/frame/moiré/QR checks
│   ├── deepfake.py            # FFT heuristic
│   ├── face_match.py          # InsightFace local 1:1 + 3-way
│   ├── face_quality.py        # Capture/face gates (used by face_match)
│   ├── document_quality.py    # Blur/brightness gates
│   ├── liveness.py            # MediaPipe EAR + motion + moiré
│   ├── gemini_scanner.py      # google-genai cloud + offline simulation
│   ├── watchlist.py           # WatchlistProvider (mocked)
│   ├── risk_engine.py         # Green/Yellow/Red + hard flags
│   ├── security_zones.py      # Legacy zone ROIs (superseded, still run)
│   ├── fairness.py            # Fairness ledger + report
│   └── vendor/models/face_landmarker.task  # Committed MediaPipe model
├── frontend/                  # React 19 + Vite + Tailwind 4 (JS/JSX, oxlint)
│   ├── src/api.js             # Base-URL + auth interceptors
│   ├── src/App.jsx            # Routes + SecurityGate
│   ├── src/views/             # Login, Dashboard, Scanner, CaseReport, AuditTrail, SecuritySetup
│   ├── src/components/        # Sidebar, SEO, Breadcrumbs
│   ├── vite.config.js         # Proxy /api→:8000, SEO files, no sourcemaps
│   └── vercel.json            # SPA rewrites + cache headers
├── samples/                   # Synthetic specimens + live bursts
│   ├── genuine_doc.png        # Valid ICAO MRZ passport
│   ├── tampered_doc.png       # Copy-move + splice
│   ├── faces/                 # person_a / person_a_2 (match) / person_b (mismatch)
│   ├── live/                  # blink_burst_*.png (12) / static_burst_*.png (8)
│   └── evidence/              # Runtime output (gitignored)
├── scripts/
│   ├── setup_vendor.sh        # Checks face_landmarker.task + system tesseract
│   └── sign_registry_import.py# Signs authority import batches (HMAC)
└── tests/
    ├── test_pipeline.py       # Checksums/demographic/watchlist/risk/Gemini/tamper<1.5s
    ├── test_auth_security.py  # Password/MFA/rate-limit/secret gates
    ├── test_face_quality.py   # Quality gates
    ├── test_physical_forgery.py # Physical checks (<5s)
    └── test_three_way.py      # Local-authoritative 3-way + sim exclusion
```

---

## 6. Getting Started

### Prerequisites
- Python 3.11+ (recommended via `uv`)
- Node.js 18+ and npm
- System Tesseract OCR (Windows: `winget install UB-Mannheim.TesseractOCR`; Debian: `sudo apt-get install -y tesseract-ocr tesseract-ocr-eng`) — no vendored binary is shipped
- Google Gemini API Key (optional — without it the scanner runs simulated; free from Google AI Studio)
- Supabase PostgreSQL account (**required** — the backend refuses to start without `DATABASE_URL`; there is no local/SQLite fallback)

### Environment Setup
```powershell
# 1. Clone the repository
git clone https://github.com/soumyajit-cys/Python Rule-Based-Fake-Identity-Document-Screening-System.git
cd Python Rule-Based-Fake-Identity-Document-Screening-System

# 2. Create virtual environment
uv venv --python 3.11 .venv
.venv\Scripts\Activate.ps1

# 3. Install Python dependencies
uv pip install -r requirements.txt

# 4. Configure environment (copy .env.example → .env):
# GEMINI_API_KEY=""            # empty = offline simulated scanner (tests rely on this)
# GEMINI_MODEL="gemini-3.6-flash"
# DATABASE_URL="postgresql://..."  # REQUIRED — Supabase; no local fallback
# APP_ENV=development JWT_SECRET=<dev default> JWT_EXPIRY_HOURS=8
# MFA_TOKEN_MINUTES=5 LOGIN_RATE_LIMIT_MAX_ATTEMPTS=5 LOGIN_RATE_LIMIT_WINDOW_SECONDS=300
# BOOTSTRAP_ADMIN_USER/PASS/UNIT (production only) REGISTRY_IMPORT_SECRET=...

# 5. Verify runtime assets:
bash scripts/setup_vendor.sh
# Checks pipeline/vendor/models/face_landmarker.task (committed; re-downloads if missing)
# and reports system tesseract + tessdata. Without tesseract, OCR/checksum
# degrade to inconclusive.

# 6. Run backend (from repo root):
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
# Auto-runs init_db + self-healing columns + seed_all(). Demo logins (non-prod):
# officer1/Officer@123, supervisor1/Supervisor@123, auditor1/Auditor@123

# 7. Run frontend (in frontend/):
npm install; npm run dev     # Vite proxy /api → 127.0.0.1:8000
npm run lint                 # oxlint
npm run build                # served by FastAPI from frontend/dist in prod

# 8. Run tests
python -m pytest tests/ -v
```

Auth notes: `POST /api/auth/login` → Bearer JWT. Supervisors complete TOTP (`/mfa/setup|verify|challenge`). `must_change_password` accounts get 403 until `/auth/change-password`. `POST /api/screen` requires `Idempotency-Key: <uuid-v4>` header (reuse on retry).

---

## 7. SIH Demo Scenarios (PRD §7)

1. **Clean Clearance:** Genuine Document + Matching Live Face + Matching DB Record ➔ **GREEN** (all local checks clear, no hard flags)
2. **Demographic Forgery:** Altered DOB/Name vs `citizens_registry` ➔ **RED / YELLOW** (field discrepancy table highlights altered field; Green forbidden)
3. **Physical Tampering:** Copy-move/spliced image ➔ **RED / YELLOW** (ELA overlay + physical-forgery zones)
4. **Identity Imposter:** Live face ≠ doc/DB (local InsightFace) ➔ **RED** (`FACE_MISMATCH`; simulated cloud alone never forces Red)
5. **Watchlist Hit:** Flagged name/ID ➔ **RED (HIGH RISK)** (`WATCHLIST_HIT`, `is_mocked=True`; violet badge still TODO — currently HIT/CLEAR chips + notice)

..................................................