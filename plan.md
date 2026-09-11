# Implementation Plan: Ultra-Fast AI Document & Identity Screening System

**Project:** Python Rule-Based Fake Identity & Document Screening System  
**Hackathon Target:** Smart India Hackathon (SIH) — Problem Statement 26188, Ministry of Home Affairs (MHA) / SSB  
**Target Environment:** Border Checkpoints & Airport Immigration Kiosks  
**Operational Requirement:** Ultra-fast, sub-2.5 second total screening latency with full forensic explainability and human-in-the-loop governance  

---

## 1. Executive Summary & Architecture Overview

At border checkpoints and airport immigration desks, security personnel must verify incoming travelers in seconds without creating long queues. This system executes an automated, parallelized forensic inspection across both the physical credential and the traveler's face:

```
                                [ TRAVELER AT KIOSK ]
                   Uploaded Document Image + Live Webcam Frame Burst
                                          │
                                          ▼
                               ┌─────────────────────┐
                               │   FastAPI Gateway   │
                               │  (Async Scheduler)  │
                               └──────────┬──────────┘
                                          │
                  ┌───────────────────────┴───────────────────────┐
                  ▼ (Parallel Async Execution)                    ▼ (Parallel Cloud AI: ~1.4s)
     Local Forensic Checks (CPU: ~0.8s)               Single-Call Gemini Multimodal AI
     • MediaPipe Blink EAR Liveness Burst             • 1. Document Classification
     • Optimized ELA Heatmap & Copy-Move              • 2. OCR Demographic Extraction
     • Algorithmic Checksums (Verhoeff / ICAO)        • 3. 3-Way Comparative Face Match
                  │                                   • 4. Forensic Visual Reasoning
                  │                                               │
                  └───────────────────────┬───────────────────────┘
                                          │
                                          ▼ (In-Memory DB Query: ~0.02s)
                        [ Demographic Database Cross-Check ]
                       Reconciles Extracted Name, DOB, Address
                           against `citizens_registry`
                                          │
                                          ▼ (Rule Engine: ~0.01s)
                                   [ RISK ENGINE ]
                           Rule-Based Composite Assessment
                               (Green / Yellow / Red)
                                          │
                  ┌───────────────────────┴───────────────────────┐
                  ▼                                               ▼
      [ OFFICER DASHBOARD ]                             [ IMMUTABLE AUDIT LOG ]
      • Document Classification Badge                   • Append-Only Event Ledger
      • Demographic Parity Table                        • Timestamped Automated Verdict
      • 3-Way Face Verification Panel                   • Officer Override & Reason
      • Interactive ELA Heatmap Overlay
      • Officer Action (Clear/Deny/Escalate)
```

---

## 2. Core Architectural Pillars

### Pillar 1: Hybrid scanner — local-authoritative face + cloud reasoning
Local InsightFace `buffalo_l` decides all face matches (CPU fallback, threshold 0.55); a single multi-image request to **Google Gemini (`google-genai` SDK, default `GEMINI_MODEL=gemini-3.6-flash`)** adds classification/OCR/reasoning, containing:
1. `Image 1`: Uploaded Document Image (Aadhaar, PAN, Voter ID, Passport)
2. `Image 2`: Live Webcam Capture Still
3. `Image 3`: Database Reference Photo (from `citizens_registry`, if found)

In a single ~1.4-second roundtrip, Gemini returns a structured JSON payload containing:
- Document type classification (`aadhaar`, `pan`, `voter_id`, `passport`) + confidence.
- Extracted demographic attributes (Full Name, Date of Birth, Gender, Document ID, Address, Father's Name).
- 3-Way Face Verification pairwise booleans (`live_vs_doc`, `doc_vs_db`, `live_vs_db`), similarity score (0.0 to 1.0), and bulleted forensic visual reasoning.
- Physical photo alteration check (detects pasted, cut, or spliced passport/ID photos).

### Pillar 2: Algorithmic Checksum Post-Processing
To eliminate any risk of AI digit hallucinations on blurry cards:
- **Aadhaar Cards:** Mathematical validation of the 12th digit using the **Verhoeff checksum algorithm**.
- **Passports:** Validation of modulus-10 check digits across Document Number, DOB, Expiry, and Composite fields per **ICAO 9303**.
- **PAN Cards:** Strict regex syntax verification (`[A-Z]{5}[0-9]{4}[A-Z]`).
- **Voter ID Cards:** EPIC alphanumeric format verification (`[A-Z]{3}[0-9]{7}`).

### Pillar 3: Database Demographic Cross-Verification
- Extracted details are automatically reconciled against the official `citizens_registry` database table.
- **Name Parity:** Token-sort / Levenshtein fuzzy string distance (tolerance >= 0.85) to accommodate initials and spacing.
- **Date of Birth Parity:** Strict date parity (instantly flags forged/altered birthdates on physical IDs).
- **Address Parity:** Locality, state, and pin code parity check.
- **Hard Rule:** Any demographic discrepancy immediately flags the case as **Yellow** or **Red**, prohibiting automatic clearance.

### Pillar 4: Local Computer Vision (Tamper, Physical, Liveness)
- **Tamper Detection:** ELA (JPEG q=90) + exact-duplicate SHA1 block-hash copy-move (tested **<1.5s** in `tests/test_pipeline.py`); physical-forgery suite (layout/MRZ-font/frame/moiré/QR) tested <5s.
- **Liveness Detection:** MediaPipe `face_landmarker.task` EAR + motion + moiré across a 14-frame burst (~2.1s in app; `MIN_BURST=3`); randomized challenges `blink/head_turn/mouth_open`.
- Runs **concurrently with the cloud AI call** via Python `asyncio` (sequential local OCR pre-pass for registry lookup is the only serial step).

### Pillar 5: Human-in-the-Loop & Audit Immutability
- **The system can only flag risk; only a human officer can deny entry.**
- For any Yellow or Red flag, an officer must record an action (`clear`, `deny`, `escalate`) with a mandatory text reason.
- Every automated assessment and human override is written to an append-only `audit_log` table.

---

## 3. Detailed Component Breakdown

### Component 1: Pipeline & AI Modules (`pipeline/`)

#### 1.1 `pipeline/checksums.py` (New Module)
- Implements:
  - `validate_verhoeff(number: str) -> bool`: Verhoeff algorithm multiplication and permutation tables for Aadhaar.
  - `validate_icao_9303(mrz_lines: list[str]) -> dict`: Modulus-10 weights (7, 3, 1) check for passport MRZ.
  - `validate_pan_format(pan: str) -> bool`: Regex validator for Indian Permanent Account Number.
  - `validate_epic_format(epic: str) -> bool`: Regex validator for Voter ID EPIC codes.

#### 1.2 `pipeline/gemini_scanner.py`
- Integrates `google-genai` (`from google import genai`, default `gemini-3.6-flash`, `response_mime_type=application/json`).
- Includes a resilient **offline simulation fallback engine** (`is_simulated=True`) so the system executes smoothly even if an API key is not yet configured or during network timeouts. Simulated face/tamper scores are excluded from Red verdicts.
- Configures strict JSON schema output:
  ```json
  {
    "document_type": "aadhaar | pan | voter_id | passport",
    "classification_confidence": 0.98,
    "demographics": {
      "document_number": "1234 5678 9012",
      "full_name": "Rajesh Kumar",
      "date_of_birth": "1988-04-12",
      "gender": "M",
      "address": "Flat 402, Shanti Vihar, New Delhi - 110001",
      "father_or_spouse_name": "Ramesh Kumar"
    },
    "three_way_face_match": {
      "live_vs_doc_match": true,
      "doc_vs_db_match": true,
      "live_vs_db_match": true,
      "similarity_score": 0.94,
      "visual_reasoning": "Consistent facial structure, identical jawline, ear geometry, and interpupillary distance across live capture and document photo."
    },
    "photo_tamper_anomaly": false
  }
  ```

#### 1.3 `pipeline/tamper.py` (Optimized Module)
- ELA (JPEG q=90 residual) + exact-duplicate SHA1 block-hash copy-move (`bs=8,stride=8,min_dist=140`; `score=0.60*copy+0.40*ela`).
- Executes in **<1.5 seconds** on CPU (asserted in `tests/test_pipeline.py`; physical suite <5s).
- Renders and saves visual Error Level Analysis (ELA) heatmap overlay image for the Case Result UI.

#### 1.4 `pipeline/demographic.py` (New Module)
- Implements `reconcile_demographics(extracted: dict, db_record: dict) -> dict`.
- Compares each attribute and generates a structured comparison list:
  ```python
  [
      {"field": "Full Name", "extracted": "Rajesh Kumar", "database": "Rajesh Kumar", "status": "match"},
      {"field": "Date of Birth", "extracted": "1995-04-12", "database": "1988-04-12", "status": "mismatch"},
      {"field": "Document ID", "extracted": "XXXX-XXXX-9012", "database": "XXXX-XXXX-9012", "status": "match"}
  ]
  ```
- Evaluates overall demographic parity and flags fraudulent date alterations.

#### 1.5 `pipeline/watchlist.py` (New Module)
- Implements `WatchlistProvider` interface and `MockWatchlistProvider`.
- Seeds high-risk test subjects (Lookout Circulars, Interpol Red Notices).
- Surfaces `is_mocked = True` to drive the required violet badge.

#### 1.6 `pipeline/risk_engine.py` (New Module)
- Aggregates:
  - Demographic Parity Status (Match / Mismatch)
  - Tamper Score (0.0 to 1.0)
  - Deepfake Score (0.0 to 1.0)
  - 3-Way Face Similarity (0.0 to 1.0)
  - Liveness Status (Live / Spoof)
  - Watchlist Status (Clear / Hit)
- Hard Flags:
  - Demographic Mismatch (Altered DOB/Name) ➔ Forces **RED** or **YELLOW**
  - Watchlist Hit ➔ Forces **RED**
  - Face Verification Mismatch ➔ Forces **RED**
  - Liveness Failure ➔ Forces at least **YELLOW**
  - Any Module Inconclusive ➔ Forces at least **YELLOW**
- Outputs: `verdict: "Green" | "Yellow" | "Red"`, `risk_score: float`, and `recommendations: list[str]`.

---

### Component 2: Backend, Database & API (`backend/`)

#### 2.1 `backend/database.py`
- Async SQLAlchemy engine supporting:
  - **Primary (Hackathon Demo & Production):** Supabase PostgreSQL (`postgresql+asyncpg://...`) — cloud-hosted PostgreSQL 15/16 with zero Windows install, live app dashboard for evaluators, and built-in object storage.
  - **Offline Fallback:** Local SQLite (`sqlite+aiosqlite:///screening.db`) — zero-setup local file database for offline environments.
- Automatically selects the connection string via `os.environ.get("DATABASE_URL")`.

#### 2.2 `backend/models.py`
- 10 ORM tables per `Schema.md`:
  1. `Officer`: id, username, password_hash (bcrypt), role, unit, must_change_password, totp_secret/enabled, password_changed_at.
  2. `CitizenRegistry`: + source/source_ref/verification_method/photo_hash/enrolled_by/approved_by/last_reconciled_at/reconciliation_status; composite unique (document_type, document_number).
  3. `RegistryEnrollment`: dual-approval queue (create/delete × pending/approved/rejected, four-eyes).
  4. `ScreeningCase`: + unit, version (optimistic locking), provenance/signature, challenge_type; status pending_review|escalated|decided.
  5. `ExtractedField`: as listed (match_status NULL when no DB record).
  6. `ModuleResultDB`: module_name tamper|physical_forgery|deepfake|liveness|gemini_ai|watchlist|checksum; is_mocked for watchlist + simulated Gemini.
  7. `OfficerAction`: RBAC-enforced (officer never deny, auditor never, escalated supervisor-only).
  8. `AuditLog`: + officer_id/session_id/request_id/device_info/file_hashes/prev_hash/entry_hash (HMAC chain).
  9. `IdempotencyRecord`: (officer_id, key) unique + input_hash + snapshot (10-min hash-window dedup).
  10. `WatchlistEntry`: mocked high-risk list behind `WatchlistProvider`.

#### 2.3 `backend/seed.py`
- Seeds test accounts:
  - Officer: `officer1` / `Officer@123`
  - Supervisor: `supervisor1` / `Supervisor@123`
  - Auditor: `auditor1` / `Auditor@123`
- Seeds official citizen reference profiles for Aadhaar, PAN, Voter ID, and Passport.

#### 2.4 `backend/app.py`
- FastAPI REST Application (canonical `/api/*`, bare legacy aliases for auth/screen/cases/audit):
  - `POST /api/auth/login|logout|mfa/challenge|mfa/setup|verify|disable|change-password`: JWT (`purpose=session`, 8h) + supervisor TOTP step-up + rotation + 5/300s throttles + unit scoping.
  - `POST /api/screen`: multipart `document_image*` + `live_capture?` + `live_frames[]?`; requires `Idempotency-Key` (UUID v4); sequential OCR pre-pass + parallel local CV + Gemini; no citizen-ID param (auto-lookup).
  - `GET /api/cases`, `GET /api/cases/{id}(+/provenance|/verify)`, `POST /api/cases/{id}/override` (RBAC + version/`If-Match`).
  - `GET /api/audit` (auditor-only) + `/verify` + `/access-review`, `GET /api/fairness/report`.
  - `GET|POST|DELETE /api/citizens*`: search, PENDING enroll, approve/reject (four-eyes), HMAC import, reconciliation report/run, orphan check/cleanup.
  - `GET /api/evidence/token/{filename}|/view?token=|/{filename}`: authenticated signed evidence (no public mount; `/evidence/*` → 404).
  - `GET /api/health`; `/{full_path}` SPA fallback from `frontend/dist` (must stay last).

---

## 4. Phased Implementation Roadmap

### Phase 1: Environment & Mathematical Core
- Create/verify Python virtual environment.
- Create `pipeline/checksums.py` with full Verhoeff (Aadhaar), ICAO 9303 (Passport), and PAN regex validators.
- Write unit tests for all mathematical checksums.

### Phase 2: AI Multi-Task Scanner & Fast CV
- Implement `pipeline/gemini_scanner.py` (`google-genai`, `gemini-3.6-flash`) for classification/OCR/reasoning alongside local InsightFace authoritative 3-way.
- Implement resilient offline simulation fallback for zero-API-key execution (simulated scores excluded from Red).
- Optimize `pipeline/tamper.py` to run in <1.5 seconds on CPU (tested); physical suite <5s.
- Implement `pipeline/demographic.py` for database reconciliation (+ trust levels).
- Implement `pipeline/watchlist.py` and `pipeline/risk_engine.py` (+ physical/quality/fairness/zones).

### Phase 3: Database & Backend API Development
- Implement `backend/database.py` (dual engine + self-healing `ensure_*`) and `backend/models.py` (10 tables).
- Implement `backend/seed.py` with mock citizens (incl. `L898902C3/Jasmine Specimen`) and officers (`officer1/supervisor1/auditor1` + `officer2`, all `must_change_password=True`).
- Implement `backend/app.py` with full `/api/*` routes (auth/MFA, idempotent screen, cases/provenance/override, audit/fairness, citizens governance, signed evidence) + JWT/RBAC.
- Measure `total_latency_ms` on `/api/screen` (sub-2.5s aspirational with added local inference).

### Phase 4: Integration Testing & SIH Presets
- Update `tests/test_pipeline.py` to cover:
  1. Genuine document + matching live face + matching DB ➔ **Green**
  2. Forged birthdate on physical document vs. DB ➔ **Yellow/Red** with discrepancy table
  3. Tampered document image (copy-move) ➔ **Red/Yellow** with ELA heatmap
  4. Imposter face / photo substitution ➔ **Red** with 3-way face mismatch
  5. Watchlist hit ➔ **Red** with violet "MOCKED DATA" badge
  6. Sub-second tamper execution assertion (< 1.5s)

---

## 5. Verification Plan

### Automated Tests
Run comprehensive pytest suite:
```powershell
python -m pytest tests/ -v
```
- Assert 100% test pass across checksums, pipeline modules, and fault isolation.

### End-to-End System Test
1. Launch backend:
   ```powershell
   python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
   ```
2. Execute automated screening tests via HTTP requests against `/api/screen` verifying response latency (< 2.5s) and correct risk verdicts.

---

## 6. Cloud Deployment & Infrastructure

To transition from local development to a production-ready environment, the following steps must be executed to deploy the application across Supabase, Render, and Vercel.

### 6.1 Database Setup (Supabase)
- **Provisioning:** Create a new PostgreSQL project on Supabase.
- **Schema Migration:** Apply the SQLAlchemy ORM schema/models to the Supabase instance.
- **Connection Details:** Retrieve the connection string (e.g., `postgresql+asyncpg://user:password@host/dbname`) and securely store it as `DATABASE_URL` in the environment variables for both local testing and Render deployment.
- **Database Seed:** Run the seed scripts (`backend/seed.py`) against the Supabase database to insert initial officers, watchlist mocks, and citizen registries.

### 6.2 Backend Deployment (Render)
- **Dependencies:** Ensure `requirements.txt` contains production-grade servers (`uvicorn`, `gunicorn`) and database adapters (`asyncpg`).
- **Configuration:** 
  - Create a new Web Service on Render, connected to the backend repository.
  - Set the Build Command: `pip install -r requirements.txt` (or equivalent).
  - Set the Start Command: `uvicorn backend.app:app --host 0.0.0.0 --port $PORT`
- **Environment Variables:** Define the following secrets in the Render dashboard:
  - `DATABASE_URL` (from Supabase; empty = SQLite fallback)
  - `JWT_SECRET` (≥32 chars; production refuses default/short), `JWT_EXPIRY_HOURS=8`, `MFA_TOKEN_MINUTES=5`
  - `GEMINI_API_KEY` (empty = simulated scanner) + `GEMINI_MODEL=gemini-3.6-flash`
  - `APP_ENV=production`, `BOOTSTRAP_ADMIN_USER/PASS/UNIT` (only prod account), `REGISTRY_IMPORT_SECRET` (or falls back to JWT_SECRET with warning)
  - `LOGIN|MFA_RATE_LIMIT_MAX_ATTEMPTS/WINDOW_SECONDS`, `DB_ECHO/POOL_SIZE/MAX_OVERFLOW`, `SCREEN_EVIDENCE_DIR`
- **CORS Configuration:** Update `backend/app.py` allowlist (currently 5173/8000 + `sih-weld-psi.vercel.app` + `netraksha.xyz`) — no wildcard.

### 6.3 Frontend Deployment (Vercel)
- **Configuration:** Link the Vercel project to the `frontend/` directory in the repository.
- **Build Settings:** Ensure the build command (`npm run build`) and output directory (`dist` or `build`) are configured correctly for the framework in use (e.g., Vite).
- **Environment Variables:**
  - Set `VITE_API_BASE_URL=https://<render-backend>/api` (must end with `/api`; DEV and `:8000` use same-origin `/api` via proxy) and `VITE_SITE_URL=https://<custom-domain>` (single source for canonical/sitemap/robots/llms.txt).
- **Routing:** If using a Single Page Application (SPA), ensure proper rewrite rules are configured (e.g., a `vercel.json` file to redirect all requests to `index.html`).
