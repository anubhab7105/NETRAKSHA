# NETRAKSHA — AI-Based Fake Identity & Document Screening System

> **Smart India Hackathon (SIH) — Problem Statement 26188**
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
- [3. System Architecture](#3-system-architecture)
- [4. Tech Stack](#4-tech-stack)
- [5. Repository Structure](#5-repository-structure)
- [6. Forensic Pipeline](#6-forensic-pipeline)
- [7. Risk Engine](#7-risk-engine)
- [8. Database Schema](#8-database-schema)
- [9. Authentication & Authorization](#9-authentication--authorization)
- [10. API Reference](#10-api-reference)
- [11. Frontend](#11-frontend)
- [12. Iris Biometrics (RGB Prototype)](#12-iris-biometrics-rgb-prototype)
- [13. Getting Started](#13-getting-started)
- [14. Configuration — Environment Variables](#14-configuration--environment-variables)
- [15. Testing](#15-testing)
- [16. Deployment](#16-deployment)
- [17. Demo Scenarios](#17-demo-scenarios)
- [18. Known Gaps & Limitations](#18-known-gaps--limitations)
- [19. License](#19-license)

---

## 1. Overview

At land border checkpoints, officers manually inspect passports, Aadhaar, PAN, Voter ID cards and the traveler's face to catch **forgeries, imposter substitution, and digitally altered documents**. Manual inspection is slow, subjective, and blind to modern physical and digital fabrication techniques (re-typeset MRZ, swapped portraits, print-scan recaptures, GAN faces, screen replay).

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

## 3. System Architecture

```
                         ┌─────────────────────────────────┐
                         │       SCREENING KIOSK (Browser)  │
                         │  React 19 + Vite 8 + Tailwind 4  │
                         │  JS/JSX only · oxlint · axios    │
                         └──────────────┬──────────────────┘
                                        │  multipart/form-data
                    ┌───────────────────┴───────────────────┐
                    │         FastAPI Gateway (single proc)  │
                    │  backend/app.py  ·  :8000  ·  /api/*  │
                    └───────────────────┬───────────────────┘
                                        │
              ┌─────────────────────────┴─────────────────────────┐
              │            FORENSIC SCREENING PIPELINE             │
              │  Sequential OCR pre-pass ─► Parallel local CV      │
              │  + Gemini cloud (asyncio.gather + run_in_executor) │
              └──────┬─────────────────┬────────────────┬──────────┘
                     │                 │                │
        ┌────────────▼──────┐ ┌────────▼────────┐ ┌─────▼─────────────┐
        │ OCR & Checksums   │ │ Tamper          │ │ Physical Forgery  │
        │ Tesseract (psm6)  │ │ ELA (q=90) +    │ │ layout / MRZ-font │
        │ PassportEye MRZ   │ │ SHA1 block-hash │ │ photo-frame / moiré│
        │ Verhoeff/ICAO/    │ │ copy-move       │ │ QR / guilloche    │
        │ PAN/EPIC + Gemini │ │ <1.5 s          │ │ <5 s              │
        └────────────┬──────┘ └────────┬────────┘ └─────┬─────────────┘
                     │                 │                │
        ┌────────────▼──────┐ ┌────────▼────────┐ ┌─────▼─────────────┐
        │ Deepfake (FFT)    │ │ Face Match (×3) │ │ Liveness + Iris   │
        │ radial spectrum   │ │ InsightFace     │ │ MediaPipe EAR +   │
        │ high_freq + peak  │ │ buffalo_l LOCAL │ │ motion + moiré    │
        │ + rolloff         │ │ 3-way hybrid    │ │ RGB iris (Hamming)│
        └────────────┬──────┘ └────────┬────────┘ └─────┬─────────────┘
                     │                 │                │
        ┌────────────▼──────┐ ┌────────▼────────┐ ┌─────▼─────────────┐
        │ Demographic       │ │ Watchlist       │ │ Gemini Scanner    │
        │ token-sort fuzzy  │ │ Provider (mock/ │ │ google-genai SDK  │
        │ DOB strict + trust│ │ DB) is_mocked   │ │ cascade + simulate│
        └────────────┬──────┘ └────────┬────────┘ └─────┬─────────────┘
                     └─────────────────┴────────────────┘
                                       │
                            ┌──────────▼──────────┐
                            │    RISK ENGINE      │
                            │ Green / Yellow / Red│
                            │ hard flags + score  │
                            └──────────┬──────────┘
                                       │
                        ┌──────────────┴──────────────┐
                        ▼                             ▼
              ┌───────────────────┐       ┌─────────────────────┐
              │ OFFICER DASHBOARD │       │ IMMUTABLE AUDIT LOG │
              │ Evidence cards    │       │ hash chain + HMAC   │
              │ 3-way verdicts    │       │ provenance bundles  │
              └───────────────────┘       └─────────────────────┘
```

**Request flow** (`backend/app.py:984`):

1. `POST /api/screen` authenticates via Bearer JWT, validates `Idempotency-Key`, hashes inputs, derives iris eye-crop from the same burst when available.
2. **OCR pre-pass** (Tesseract + PassportEye) extracts demographics for registry lookup.
3. **Parallel stage** — `asyncio.gather` runs local CV (`tamper`, `physical_forgery`, `deepfake`, `liveness`, local 3-way `face_match`, iris) concurrently with the **Gemini cloud call** (cascading model fallback, 10 s per-model timeout).
4. **Reconciliation** — demographic fuzzy match + registry trust tier + watchlist lookup + iris verification.
5. **Risk engine** produces verdict/flags/recommendations; the case, fields, module results, provenance, and audit entries are persisted.
6. Evidence PNGs are written to `SCREEN_EVIDENCE_DIR` or `samples/evidence/` and served only via **signed, expiring URLs** (`/api/evidence/token|view|{filename}`).

---

## 4. Tech Stack

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

## 5. Repository Structure

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

## 6. Forensic Pipeline

### 6.1 Contract

Every `run_*` obeys the non-negotiable contract (`pipeline/common.py:104`):

```python
ModuleResult(
    module_name: str,          # e.g. "tamper", "face_match"
    score: float | None,       # 0–1 when ok, None when inconclusive (clipped via np.clip)
    status: "ok" | "inconclusive",
    raw_output: dict,          # full evidence for UI + audit (reason[:200] when inconclusive)
    evidence_uri: str | None,  # path to evidence PNG or None
)
```

Helpers: `ok_result(...)` and `inconclusive_result(module, reason)` (`pipeline/common.py:144`). **Any `inconclusive` forces verdict ≥ Yellow** (`pipeline/risk_engine.py:226`).

| Rule | Effect |
|---|---|
| Evidence-write failures | Swallowed, logged, never crash the case |
| `physical_forgery` sub-checks | Each isolated in `try/except` — one broken check never kills the module |
| `POST /api/screen` | Never 500s on module failure — faults degrade, the case always completes |

### 6.2 Modules

| # | Module | File | Engine | What it detects | Evidence |
|---|---|---|---|---|---|
| 1 | **OCR & MRZ** | `pipeline/ocr_mrz.py` | Tesseract `pytesseract --psm 6` + PassportEye MRZ + regex + Gemini classifier | Full Name, DOB, Doc Number, Address/Father's Name, ICAO 9303 checksums | Parsed MRZ + ICAO block checks |
| 2 | **Checksums** | `pipeline/checksums.py` | Pure Python: Verhoeff (Aadhaar-12), ICAO (7,3,1), `[A-Z]{5}[0-9]{4}[A-Z]` (PAN), `[A-Z]{3}[0-9]{7}` (EPIC) | Eliminates AI digit hallucination; dispatch via `validate_document_number` | `valid` + `method` |
| 3 | **Demographic** | `pipeline/demographic.py` | Token-sort Levenshtein (name ≥ 0.85, addr ≥ 0.60) + strict DOB/ID | Cross-references `citizens_registry`; critical fields: Full Name, DOB, Document Number | `comparisons[]`, `mismatch_fields`, `critical_mismatches` |
| 4 | **Tamper** | `pipeline/tamper.py` | **ELA** (JPEG q=90 residual, JET overlay) + **exact-duplicate SHA1 block-hash copy-move** (not ORB/NCC) | Splicing + copy-move duplicates; must be **< 1.5 s** (tested) | `tamper_<id>.png` ELA overlay |
| 5 | **Physical Forgery** | `pipeline/physical_forgery.py` | 6 deterministic sub-checks: `layout` (aspect + MRZ lines + portrait zone) · `font_consistency` (MRZ monospace lattice + stroke CV) · `photo_boundary` (quad + frame remnants) · `print_scan` (FFT moiré + acutance) · `qr_barcode` (OpenCV + pyzbar) · `security_features` (guilloche prominence) — weighted mean over available checks (<5 s) | Re-typeset MRZ, swapped photo, print-scan counterfeits that ELA misses | Zone overlay `physical_<id>.png` |
| 6 | **Deepfake** | `pipeline/deepfake.py` | `numpy.fft.fft2` radial spectrum (`high_freq + peakedness + rolloff`), **no pretrained CNN** | GAN upsampling artifacts | `method=fft_frequency_artifact_heuristic` |
| 7 | **Face Match (hybrid)** | `pipeline/face_match.py` | **Local authoritative:** InsightFace `buffalo_l` (ArcFace `w600k_r50`, cosine, threshold **0.55**, `CPUExecutionProvider`) for all pairs with both inputs; **Cloud:** Gemini 3-way reasoning (`pipeline/gemini_scanner.py`); simulated cloud scores **excluded from verdict** | `live ↔ doc` (primary), `doc ↔ DB`, `live ↔ DB` via `run_three_way_match` | Side-by-side PNG + completeness `complete/partial/unavailable` |
| 8 | **Liveness** | `pipeline/liveness.py` | MediaPipe `face_landmarker.task` (468-pt EAR, adaptive threshold) + inter-frame motion + FFT moiré + head-yaw/mouth-open; challenges `blink / head_turn / mouth_open` ; `MIN_BURST=3`, `LIVE_THRESHOLD=0.45` | 14-frame burst defeats photo/screen replay; challenge miss is `challenge_not_observed:*` not a fail when another genuine action occurred | `blink_count`, `motion_score`, `screen_artifact_score` |
| 9 | **Iris** | `pipeline/iris.py` → `backend/biometric/iris/` | Classical Hough circles → polar unwrap (64×512) → Gabor → 512-byte template; Hamming threshold **0.32** (low-conf band 0.28–0.36) | RGB eye verification + PAD (temporal + moiré) | `quality`, `liveness`, `hamming_distance` |
| 10 | **Watchlist** | `pipeline/watchlist.py` | `WatchlistProvider` / `MockWatchlistProvider` (5 fictional entries) or DB-backed via `load_db_watchlist_provider` | `is_hit`, `is_mocked=True` controls violet **MOCKED DATA** badge | `hits[]`, `is_mocked` |
| — | **Quality / Fairness / Zones** | `pipeline/document_quality.py` · `pipeline/face_quality.py` · `pipeline/fairness.py` · `pipeline/security_zones.py` | Laplacian blur ≥ 50, brightness; face gates (blur/light/size/pose); in-memory fairness ledger; legacy ROIs | Gates (`recapture_requested`) + `GET /api/fairness/report` | Not standalone verdicts |

**Thresholds** — single source `pipeline/thresholds.json:1` (v1.0):

```json
{
  "face_match": 0.55, "face_low_conf_low": 0.45, "face_low_conf_high": 0.65,
  "tamper_high": 0.7, "tamper_moderate": 0.4,
  "deepfake_high": 0.7, "liveness": 0.45,
  "document_quality_blur": 50.0,
  "iris_match": 0.32, "iris_low_conf_low": 0.28, "iris_low_conf_high": 0.36
}
```

Calibrated on `samples/genuine_doc.png` (tamper 0.08) vs `samples/tampered_doc.png` (0.72), face pairs 0.93–0.95. Iris band is an **uncalibrated prototype** — re-tune on held-out data before production.

---

## 7. Risk Engine

`pipeline/risk_engine.py:43` — `assess_risk(...) -> RiskAssessment(verdict, risk_score, flags, recommendations, module_summary)`

**Composite score** = mean of per-module risk components (0–1), then mapped:

```
Green  < 0.35 <  Yellow  < 0.65 <  Red
```

Hard flags **escalate** the minimum verdict (never de-escalate) — `_escalate` is `max(level)` (`pipeline/risk_engine.py:403`):

| Signal | Flag | Floor |
|---|---|---|
| `critical_mismatches` (Name/DOB/ID) | `DEMOGRAPHIC_CRITICAL_MISMATCH:*` | **Red** |
| Minor mismatches | `DEMOGRAPHIC_MISMATCH:*` | Yellow |
| `citizens_registry` trust `unverified` | `UNVERIFIED_REGISTRY_SOURCE` | **Yellow** (Green forbidden) |
| `legacy` trust | `LEGACY_REGISTRY_NEEDS_REVERIFICATION` | informational |
| Local face `live ↔ doc` mismatch (`match==False`, outside low-conf band) | `FACE_MISMATCH` | **Red** |
| Low-conf face band 0.45–0.65 | `FACE_LOW_CONFIDENCE:0.xxx` | **Yellow** (bias mitigation — always manual review) |
| Evidence-backed registry mismatch (`db_face_pairs.evidence=="local"` + `doc_vs_db`/`live_vs_db == False`) | `DOC_DB_FACE_MISMATCH` / `LIVE_DB_FACE_MISMATCH` | **Red** (simulated guesses ignored) |
| Watchlist hit | `WATCHLIST_HIT` | **Red** |
| Tamper ≥ 0.7 / ≥ 0.4 | `HIGH_TAMPER_SCORE` / `MODERATE_TAMPER_SCORE` | **Red** / Yellow |
| Physical ≥ 0.7 / ≥ 0.4 | `HIGH_PHYSICAL_FORGERY_SCORE` / `MODERATE_…` | **Red** / Yellow |
| Deepfake ≥ 0.7 | `HIGH_DEEPFAKE_SCORE` | **Yellow** |
| Liveness `live==False` | `LIVENESS_FAILURE` | **Yellow** |
| Any module `inconclusive` | `*_INCONCLUSIVE` | **Yellow** |
| Iris mismatch / poor quality / liveness fail | `IRIS_MISMATCH` / `IRIS_QUALITY_POOR` / `IRIS_LIVENESS_FAILED` | **Red** / Yellow / Yellow |

Bias note: the face low-confidence band routes near-threshold scores to manual review to avoid unfair targeting of groups where the model is less certain.

---

## 8. Database Schema

**11 tables** (`backend/models.py:1`) — Supabase PostgreSQL in production, SQLite (`aiosqlite`) only for isolated `:memory:` fixtures in `tests/test_auth_security.py`.

```
officers  ─┬─< screening_cases ─┬─< extracted_fields
           │                    ├─< module_results
           │                    ├─< officer_actions
           │                    └─< (provenance, version, unit, challenge_type)
           └─< officer_actions
                registry_enrollments (dual-approval queue)
citizens_registry ─┬─< screening_cases
                   └─< iris_templates (encrypted, per-eye)

audit_log (append-only, hash-chained: prev_hash → entry_hash via HMAC-SHA256)
screening_idempotency (uq: officer_id+key, ix: officer+session+input_hash)
watchlist_entries (mocked or real)
```

| Table | Key columns |
|---|---|
| `officers` | `username` (unique), `password_hash` (bcrypt), `role` (`officer`/`supervisor`/`auditor`), `unit` (`BORDER_UNIT_1`/`BORDER_UNIT_2`/`HQ`), `must_change_password`, `totp_secret`/`totp_enabled`, `password_changed_at` |
| `citizens_registry` | `document_type`/`document_number` (unique together), `full_name`, `date_of_birth`, `gender`, `address`, `photo_uri` (local path **or** `http(s)` / Storage path `img/<object>`), trust: `source`/`source_ref`/`verification_method`/`photo_hash`/`enrolled_by`/`approved_by`/`reconciliation_status` |
| `registry_enrollments` | `action` (`create`/`delete`), `status` (`pending`/`approved`/`rejected`), staged payload + `requested_by`/`approved_by`, `target_citizen_id`/`resulting_citizen_id` |
| `screening_cases` | `officer_id`, `citizen_id`, `document_type`, `verdict` (`Green`/`Yellow`/`Red`), `status` (`pending_review`/`escalated`/`decided`), `risk_score`, `unit`, `version` (optimistic locking), `provenance` (JSON) + `provenance_signature` (HMAC), `challenge_type` |
| `extracted_fields` | `case_id`, `field_name`, `extracted_value`/`database_value`, `match_status` (`match`/`mismatch`/`unverified`), `confidence` |
| `iris_templates` | `citizen_id`, `template` (base64 encrypted), `mask`, `quality`, `eye` (`left`/`right`), `enrolled_by` |
| `module_results` | `case_id`, `module_name`, `score`, `status` (`ok`/`inconclusive`), `raw_output` (JSON), `evidence_uri`, `is_mocked` |
| `officer_actions` | `case_id`, `officer_id`, `action` (`clear`/`deny`/`escalate`), `reason` (≥ 3 chars) |
| `audit_log` | `actor`, `action`, `entity`, `immutable`, `officer_id`, `session_id` (JWT `jti`), `request_id`, `device_info`, `file_hashes` (JSON), `prev_hash`, `entry_hash` (HMAC chain) |
| `screening_idempotency` | `idempotency_key` (128), `officer_id`, `session_id`, `input_hash` (SHA-256), `case_id`, `response_snapshot` (JSON), `created_at` |
| `watchlist_entries` | `name`, `id_number`, `flag_reason` |

**Startup self-heal** (`backend/database.py:103` — `init_db`):

- `ensure_model_columns()` — adds any ORM-mapped column missing from the live DB (Postgres `information_schema` / SQLite `PRAGMA`).
- `ensure_registry_trust_columns()` / `ensure_auth_columns()` — backfills post-audit columns.
- `ensure_sequences()` — re-anchors `SERIAL` sequences past `max(id)` on Postgres (legacy explicit-ID DBs).
- Backfills `NULL` flags (`must_change_password`, `totp_enabled`, `version`).

Registry photos: `_resolve_db_photo()` downloads `http(s)` or Supabase Storage `img/<object>` refs once into `$TMPDIR/netraksha_registry_photos` (8 s timeout, 5 MB cap, magic-byte check) for both Gemini Image 3 and local 3-way. Failures degrade to `partial` with `db_pairs_unavailable_reason` (`no_registry_photo` | `registry_photo_missing_on_server` | `registry_photo_download_failed`), never halt.

---

## 9. Authentication & Authorization

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

## 10. API Reference

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
| `POST` | `/api/evidence/token` | Mint signed URL for an evidence file (`expires_in` 30–3600 s) |
| `GET` | `/api/evidence/view?token=` | Authenticated evidence view (no public `/evidence/*` mount) |
| `GET` | `/api/evidence/{filename}` | Signed direct fetch |

### Registry (controlled enrollment)

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/registry/enroll` | Supervisor requests `create`/`delete` — enters `pending` queue |
| `GET` | `/api/registry/enrollments` | List enrollments (status filter) |
| `POST` | `/api/registry/enrollments/{id}/approve` | **Different** supervisor approves (four-eyes) — writes `citizens_registry` |
| `POST` | `/api/registry/enrollments/{id}/reject` | Reject with `review_note` |
| `POST` | `/api/registry/import` | HMAC-signed authority batch import (header `X-Registry-Signature`) |
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

**CORS** allowlist (`backend/app.py:275`): `localhost:5173`, `127.0.0.1:5173`, `localhost:8000`, `127.0.0.1:8000`, `sih-weld-psi.vercel.app`, `netraksha.xyz` (+ `www`/`api`), `web-production-ab06a.up.railway.app` + `CORS_ORIGINS` extra. Unhandled 500s preserve CORS headers; `HTTPException` handler ensures 401/403 carry CORS.

---

## 11. Frontend

`frontend/` — **React 19 + Vite 8 + Tailwind 4**, **JS/JSX only (no TypeScript)**, `oxlint` for linting.

| View | Route | Purpose |
|---|---|---|
| **Login** | `/login` | Username/password → JWT or `mfa_token` step-up; handles `PASSWORD_CHANGE_REQUIRED`/`MFA_SETUP_REQUIRED` 403s |
| **SecuritySetup** | `/change-password` | Forced password rotation + TOTP enrollment (QR + manual key + server time) |
| **Dashboard** | `/` | Case queue with verdict/status/unit filters, pagination, role-aware actions |
| **Scanner** | `/scan` | `WebcamCapture` (document `environment` + person burst) — 14-frame burst for liveness, downscaled JPEG for doc; `PersonBiometricCapture` feeds face+liveness+iris from **one** capture; `Idempotency-Key` minted per intent, regenerated on input change |
| **CaseReport** | `/case/:id` | Evidence cards (ELA, physical overlay, face side-by-side), demographic parity table, 3-way face completeness, liveness + iris signals, risk flags + recommendations, override form (optimistic locking) |
| **AuditTrail** | `/audit` | Hash-chained ledger with actor/action/entity filters + chain verification |
| **NotFound** | `*` | 404 |

**Key client details** (`frontend/src/api.js:1`, `frontend/vite.config.js:1`):

- `resolveBaseURL()` — `DEV` or `:8000` → same-origin `/api`; `netraksha.xyz`/`www`/`sih-weld-psi.vercel.app`/`*.up.railway.app` → `/api` (avoids CORS); otherwise `VITE_API_BASE_URL` (must end `/api`) or fallback `/api`.
- Interceptors — attach `Authorization`, wipe `localStorage` + redirect to `/login` on 401 (except step-up URLs), redirect to `/change-password` on 403 rotation/MFA gates.
- `apiErrorMessage` — unwraps FastAPI 422 array `detail` into human-readable `HTTP <status>: <msg>`.
- `GovTopBar` / `Sidebar` / `SEO` / `Breadcrumbs` / `ui` (`GovNotice`, `WorkflowSteps`, `PageHeader`).
- `vite.config.js` — `seoFiles()` emits `robots.txt`/`sitemap.xml`/`llms.txt` and replaces `%SITE_URL%` in `index.html`; `sourcemap:false` intentional; `manualChunks` for `react-vendor`/`router`/`lucide-icons`/`http-client`.

---

## 12. Iris Biometrics (RGB Prototype)

> **Disclosure:** The current iris path is a **smartphone RGB prototype, not a dedicated NIR system**. See `docs/iris_architecture.md:1` and the `IrisCapture` UI notice. Expected EER is 5–15 % (vs 1–2 % for 850 nm NIR) and degrades with ambient light, distance, reflections, pupil dilation, and dark irises.

| Stage | Implementation |
|---|---|
| **Provider interface** | `BiometricProvider` (`backend/biometric/iris/provider.py`) — `RGBProvider` (current) + `NIRProvider` (stub, `ctypes`/`pyusb` path) via `get_provider("rgb"|"nir")` |
| **Segmentation** | Classical Hough circles on eye crop (`segmenter.py`) |
| **Normalization** | Polar unwrapping `64×512` (`normalizer.py`) |
| **Encoding** | Single Gabor filter → binary template `64×8` → 512 bytes (`encoder.py`) |
| **Matching** | Hamming distance, threshold `0.32` (low-conf band `0.28–0.36`) (`matcher.py`, `pipeline/thresholds.json:12`) |
| **Quality** | Blur, illumination, iris area (`quality.py`) |
| **PAD** | Temporal movement + FFT moiré + screen replay (`liveness.py`) |
| **Storage** | `iris_templates.template` encrypted at rest (HMAC+base64; production should use `Fernet`/`AES-GCM` with `IRIS_ENCRYPTION_KEY`); raw eye images deleted after enrollment (`unlink`) |

No learned weights yet. Future training data: `UBIRIS.v2`, `CASIA-Iris-Thousand` (check licenses), with heavy augmentation for phone capture.

---

## 13. Getting Started

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
  <sub>Built for SIH 2026 · PRD §7 · Techspec §5 · Rules.md</sub>
</p>
