# Product Requirements Document (PRD)
## Python Rule-Based Fake Identity & Document Screening System — MVP

### 1. Background
Smart India Hackathon — Problem Statement 26188, Ministry of Home Affairs (SSB). The source architecture document describes the full production vision; this PRD scopes what the team is actually building right now.

### 2. Problem statement
Border checkpoint officers manually inspect travel/identity documents and faces for forgery, tampering, and identity mismatch. This is slow, inconsistent, and misses sophisticated forgeries and deepfakes. The goal is an AI-assisted screening tool that flags risk (Green/Yellow/Red) and gives an officer explainable evidence to make the final call — never an automatic denial.

### 3. Goals for this build
- Demonstrate an end-to-end pipeline: capture → OCR extraction + checksums → database demographic cross-verification (Name, DOB, Address, Doc ID) → tamper & physical-forgery & deepfake checks → hybrid face verification (local InsightFace authoritative + Gemini reasoning) → liveness → risk verdict → officer dashboard.
- Every verdict must show *why* (per-module evidence, demographic field comparisons, 3-way facial pairs, ELA/physical overlays), not just a score.
- Human-in-the-loop is structural: only a human can deny; the system can only flag.
- Multi-document support tailored for Indian identity documents (Aadhaar, PAN, Voter ID, Passport) alongside international travel credentials.

### 4. Non-goals for this build
- Real production integration with live UIDAI (Aadhaar) / NSDL (PAN) / ECI (Voter ID) APIs (mocked local registry + `WatchlistProvider` used instead).
- Kubernetes/microservices/Kafka — single FastAPI process only, matches prototype architecture.
- Demographic bias/fairness certification, penetration testing, DPDP compliance sign-off (a fairness ledger/report exists as telemetry only — `GET /api/fairness/report` — not a certification).
- Multi-checkpoint, multi-tenant, HA/failover.

### 5. Target users (for the demo)
- **Primary persona:** Border/checkpost officer reviewing a traveler's document + face at a kiosk.
- **Secondary:** A supervisor/auditor viewing cases, reconciliation, and the audit trail. RBAC: officers see own cases and cannot `deny` (must escalate); supervisors see own unit + enroll/approve registry; auditors are read-only but see all cases + audit.
- **Audience for the demo itself:** SIH evaluators — the UI should make the reasoning visible, not just the verdict.

### 6. MVP scope — Pipeline & Verification Modules
| Module | MVP approach (as built) |
|---|---|
| OCR & Field Extraction | Tesseract + PassportEye + regex (local) plus Gemini `gemini-3.6-flash` classifier/OCR (`google-genai` SDK) with offline simulation fallback |
| Checksums | Verhoeff (Aadhaar-12), ICAO 9303 (7,3,1) (Passport), PAN/EPIC regex |
| Demographic DB Cross-Check | Field-by-field vs `citizens_registry` (name fuzzy ≥0.85, strict DOB/ID, address ≥0.60) |
| Tamper detection | ELA + exact-duplicate SHA1 block-hash copy-move (classical CV), ELA overlay evidence |
| Physical forgery | Layout / MRZ-font / photo-frame / print-scan moiré / QR / guilloche-hologram inventory |
| Deepfake detection | FFT frequency-artifact heuristic (no trained CNN) |
| Face Verification (hybrid) | Local InsightFace `buffalo_l` (authoritative matches) + Gemini 3-way reasoning (Live vs Doc, Doc vs DB, Live vs DB) |
| Liveness | MediaPipe FaceLandmarker EAR + motion + moiré; challenges `blink/head_turn/mouth_open` |
| Watchlist/DB lookup | Mocked table behind `WatchlistProvider` (`is_mocked=True`) |
| Quality / fairness / zones | `document_quality`, `face_quality` gates, `security_zones` legacy ROIs, `fairness` ledger |

### 7. Success criteria for the demo
- **Clean Traveler:** Genuine sample document (e.g. Aadhaar/Passport) + matching database demographic record + matching local face pairs → Green.
- **Demographic Forgery / Data Tampering:** Altered Name/DOB/Address vs `citizens_registry` → flagged Red/Yellow with field-level discrepancy highlighted (Green forbidden).
- **Physical Tampering:** Tampered/altered document image → flagged Red/Yellow with ELA heatmap + physical-forgery overlay.
- **Face Imposter / Photo Substitution:** Person does not match doc/DB (local InsightFace) → flagged Red with pair breakdown. Simulated-cloud mismatch alone does not force Red.
- **Watchlist Hit:** Flagged subject → flagged Red with mocked-source indication (`is_mocked=True`; violet badge is a known UI gap — currently chips + notice).
- **Audit Logging:** Every automated check, demographic mismatch, and officer decision is logged to the hash-chained audit trail (`GET /api/audit`, `GET /api/audit/verify`).

### 8. Assumptions & open questions — resolved
- **Deepfake detector:** resolved as FFT/spectral heuristic (`pipeline/deepfake.py`, `method=fft_frequency_artifact_heuristic`). No trained classifier. Revisit only with a labeled set.
- **Storage:** resolved as dual-engine — Supabase PostgreSQL primary (`DATABASE_URL`) + local SQLite fallback (`screening.db`). Schema self-heals at startup; 10 tables (see `Schema.md`).
- **Auth:** resolved as real auth — bcrypt (passlib only) + JWT + supervisor TOTP + forced rotation + rate limits + unit scoping. Demo logins `officer1/Officer@123`, `supervisor1/Supervisor@123`, `auditor1/Auditor@123` (non-prod only).
- **Sample data:** resolved — `samples/genuine_doc.png` (valid ICAO MRZ), `samples/tampered_doc.png`, `faces/person_a|a_2|b.png`, `live/blink_burst_*|static_burst_*`, `vendor/models/face_landmarker.task`. Registry seed includes `L898902C3 / Jasmine Specimen` matching the specimens.
- **Sprint length:** ~6 days (see `Implementationplan.md`; build is substantially complete — see `Tracker.md`).

### 9. Future / production vision (reference only — not in MVP scope)
Condensed from the source architecture doc, for context on where this heads after the hackathon:
- Microservices behind an API Gateway + Kafka message queue, independently scalable per module
- Kubernetes on government-empanelled cloud (MeghRaj/NIC) or on-prem, with edge deployment for low-connectivity checkpoints
- Real integration with national ID registries/watchlists via a secure abstraction layer (biggest lead-time item — inter-agency approval, not engineering)
- Trained CNN/transformer models replacing every classical-CV component, retrained continuously
- Full DPDP Act compliance, RBAC hardening, immutable audit logging, HSM-managed encryption, third-party security audit
- 5-phase, ~12-month build-out (see Implementation Plan appendix)
