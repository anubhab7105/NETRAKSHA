# Implementation Plan
## MVP — ~6-Day Sprint

Confirmed for this build: **GPU available**, **~6 days**, sample specimen documents/test faces **partially available** (gap to close — see Day 1), storage is **PostgreSQL** (not SQLite), and the officer dashboard needs **real login** (not the mock login originally floated). Each day below reflects those confirmations.

This plan sequences the 6 pipeline modules from `Prd.md` §6 / `Techspec.md` §3, plus the newly-confirmed Postgres + real-auth work. It assumes one team working roughly in parallel across backend/ML and frontend — adjust freely if your actual team split differs (team composition wasn't specified, so no roles are assumed below beyond "backend/ML" and "frontend" as work streams, not job titles).

---

### Day 1 — Foundations, Database & Specimen Registries
- Stand up FastAPI single-process skeleton with the 7 real endpoints (`/login`, `/logout`, `/screen`, `/cases`, `/cases/{id}`, `/cases/{id}/override`, `/audit`).
- Stand up database (PostgreSQL/SQLite dual async engine) and apply `Schema.md` tables, including `officers` and `citizens_registry`.
- Seed test citizen database records: Aadhaar, PAN, Voter ID, and Passport records with names, DOBs, addresses, and reference photos.
- Build the `officers` table + real login (username/password, JWT/session tokens).
- Scaffold the React + TS + Vite + Tailwind frontend shell with login and navigation.

### Day 2 — Document Classifier, Demographic Verification & Tamper
- Implement Document Classifier: Python rule-based visual/text scanning identifying document type (`aadhaar`, `pan`, `voter_id`, `passport`).
- Implement specialized OCR & field extraction (Tesseract + PassportEye + regex parsers) for UID, PAN, EPIC, Passport MRZ, Name, DOB, Address.
- Implement Database Demographic Cross-Verification: Query `citizens_registry` by document number and verify Name (fuzzy matching), DOB (strict parity), and Address.
- Implement Tamper detection: ELA + Block NCC copy-move, producing evidence overlay image.
- Wire into `/screen` with fault isolation ("module failure → inconclusive, never crash").
- Frontend: Capture screen with document classification preview + Demographic Reconciliation table.

### Day 3 — 3-Way AI Face Verification + Liveness
- Face verification (3-Way Multimodal AI): Google Gemini 1.5/2.0 Flash API integration via `google-generativeai`. Accepts Document Photo Crop + Live Webcam Still + Database Record in a single prompt. Returns pairwise match booleans (Live vs Doc, Doc vs DB, Live vs DB), similarity score, and bulleted biometric explainability. Completely bypasses local C++ build and GPU dependency barriers.
- Liveness: blink/EAR heuristic across a webcam frame burst (MediaPipe FaceLandmarker).
- Frontend: webcam capture widget (frame burst + still) + 3-image Face Verification & Liveness evidence panels.

### Day 4 — Deepfake detection + Watchlist (mocked) + Risk Engine
- Deepfake detection: FFT frequency-artifact heuristic (radial power spectrum and high-frequency peakedness).
- Watchlist: mocked lookup table behind `WatchlistProvider` (Techspec §3, Schema.md `watchlist_entries`) — ensure `is_mocked` is set and surfaced with violet badge.
- Risk Engine: weighted rule-based scoring → Green/Yellow/Red with hard flags (Demographic mismatch ➔ Red/Yellow, Watchlist hit ➔ Red, Face mismatch ➔ Red, Failed liveness ➔ Yellow).
- Frontend: Deepfake/Watchlist panels, verdict banner, decision panel (`POST /cases/{id}/override`).

### Day 5 — Integration testing + audit trail + case history
- Run the full pipeline end-to-end against the specimen set assembled/closed on Day 1, against every success criterion in Prd.md §7 (genuine match → Green; tampered → Yellow/Red with evidence; face mismatch → flagged with score; watchlist hit → Red with mocked label visible; every case → audit entry).
- Implement `GET /cases`, `GET /cases/{id}`, `GET /audit` and the corresponding Dashboard / Case Detail / Audit Trail screens (AppFlow.md §3.2, 3.5, 3.6).
- Fix whatever the integration run surfaces — this is the day most likely to slip; the buffer on Day 6 exists for this reason.

### Day 6 — Hardening, demo rehearsal, buffer
- Error-path pass: force each module to fail individually, confirm "inconclusive" behavior end-to-end (Techspec §5, AppFlow.md §4) — this is a specific SIH evaluator-visible reliability story, worth protecting.
- Full run-through of the demo script against Prd.md §7 criteria, timed.
- Buffer for anything from Days 1–5 that slipped, and for closing out open items in Tracker.md that are still unresolved.

---

### Explicitly out of this plan (Prd.md §4 non-goals)
Kubernetes/microservices/Kafka, real national DB/watchlist integration, demographic bias/fairness certification, penetration testing, DPDP sign-off, multi-checkpoint/multi-tenant/HA. See the source architecture PDF §11 for where these land in the post-hackathon roadmap.