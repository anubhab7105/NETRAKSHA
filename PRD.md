# Product Requirements Document (PRD)
## Python Rule-Based Fake Identity & Document Screening System — MVP

### 1. Background
Smart India Hackathon — Problem Statement 26188, Ministry of Home Affairs (SSB). The source architecture document describes the full production vision; this PRD scopes what the team is actually building right now.

### 2. Problem statement
Border checkpoint officers manually inspect travel/identity documents and faces for forgery, tampering, and identity mismatch. This is slow, inconsistent, and misses sophisticated forgeries and deepfakes. The goal is an AI-assisted screening tool that flags risk (Green/Yellow/Red) and gives an officer explainable evidence to make the final call — never an automatic denial.

### 3. Goals for this build
- Demonstrate an end-to-end pipeline: capture → document classification (Aadhaar / PAN / Voter ID / Passport) → OCR extraction → database demographic cross-verification (Name, DOB, Address, Doc ID) → tamper & deepfake checks → 3-way AI face verification → liveness → risk verdict → officer dashboard.
- Every verdict must show *why* (per-module evidence, demographic field comparisons, 3-way facial reasoning), not just a score.
- Human-in-the-loop is structural: only a human can deny; the system can only flag.
- Multi-document support tailored for Indian identity documents (Aadhaar, PAN, Voter ID, Passport) alongside international travel credentials.

### 4. Non-goals for this build
- Real production integration with live UIDAI (Aadhaar) / NSDL (PAN) / ECI (Voter ID) APIs (mocked local registry database used instead).
- Kubernetes/microservices/Kafka — single process, matches prototype architecture.
- Demographic bias/fairness certification, penetration testing, DPDP compliance sign-off.
- Multi-checkpoint, multi-tenant, HA/failover.

### 5. Target users (for the demo)
- **Primary persona:** Border/checkpost officer reviewing a traveler's document + face at a kiosk.
- **Secondary:** A supervisor/auditor viewing the audit trail.
- **Audience for the demo itself:** SIH evaluators — the UI should make the reasoning visible, not just the verdict.

### 6. MVP scope — Pipeline & Verification Modules
| Module | MVP approach |
|---|---|
| Document Classification | Rule-based & visual scanning: identifies document type (Aadhaar Card, PAN Card, Voter ID / EPIC, Passport) |
| OCR & Field Extraction | Specialized parsers for Aadhaar (UID, Name, DOB, Address), PAN (PAN No, Name, Father's Name, DOB), Voter ID (EPIC No, Name, Age/DOB), Passport (MRZ + ICAO 9303 check digits) |
| Demographic DB Cross-Check | Field-by-field verification of extracted details against existing database records (Name, DOB, Address, Document ID) |
| Tamper detection | ELA + Block NCC / ORB copy-move (classical CV) |
| Deepfake detection | FFT frequency-artifact heuristic (spectral peakedness) |
| 3-Way AI Face Verification | Multimodal Vision AI (Gemini 1.5/2.0 Flash): 3-way comparative verification (Live Webcam Capture vs. Document Photo Crop vs. Database Reference Photo) with explainable forensic analysis |
| Liveness | Blink/EAR-based frame-burst heuristic (MediaPipe) |
| Watchlist/DB lookup | Mocked local lookup table behind an abstraction interface (`WatchlistProvider`) |

### 7. Success criteria for the demo
- **Clean Traveler:** Genuine sample document (e.g. Aadhaar/Passport) + matching database demographic record + matching 3-way face verification → Green, auto-clear.
- **Demographic Forgery / Data Tampering:** Uploaded document with altered Name/DOB/Address compared to the official database record → flagged Red/Yellow with field-level discrepancy highlighted.
- **Physical Tampering:** Tampered/altered document image → flagged Red/Yellow with visible ELA heatmap evidence.
- **Face Imposter / Photo Substitution:** Document photo altered or person does not match document/DB record → flagged Red/Yellow with multi-image discrepancy breakdown.
- **Watchlist Hit:** Flagged subject → flagged Red with mocked-DB label clearly shown as mocked.
- **Audit Logging:** Every automated check, demographic mismatch, and officer decision is logged to the audit trail.

### 8. Assumptions & open questions (flag to confirm)
- **Deepfake detector:** no trained classifier is feasible in days — MVP will use a pretrained open-source model or a frequency-domain heuristic. Confirm if you have a preferred model/dataset.
- **Storage:** SQLite for the local demo (vs. Postgres in production) — confirm if you'd rather set up Postgres locally too.
- **Auth:** a simple mock login (no real auth backend) for the officer dashboard — confirm if a real login is needed for the demo.
- **Sample data:** needs a set of genuine + tampered specimen documents and test faces — none exist yet; the team needs to source/create these (see Implementation Plan).
- **Exact number of days available** isn't specified — the Implementation Plan assumes a ~6-day sprint; adjust freely.

### 9. Future / production vision (reference only — not in MVP scope)
Condensed from the source architecture doc, for context on where this heads after the hackathon:
- Microservices behind an API Gateway + Kafka message queue, independently scalable per module
- Kubernetes on government-empanelled cloud (MeghRaj/NIC) or on-prem, with edge deployment for low-connectivity checkpoints
- Real integration with national ID registries/watchlists via a secure abstraction layer (biggest lead-time item — inter-agency approval, not engineering)
- Trained CNN/transformer models replacing every classical-CV component, retrained continuously
- Full DPDP Act compliance, RBAC, immutable audit logging, HSM-managed encryption, third-party security audit
- 5-phase, ~12-month build-out (see Implementation Plan appendix)