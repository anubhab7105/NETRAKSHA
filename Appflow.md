# App Flow
## Python Rule-Based Fake Identity & Document Screening System — MVP

Scope note: this describes the flow for the MVP build only (single checkpoint, single process, per `Prd.md` / `Techspec.md`). Production-scale flow (multi-checkpoint, WebSocket push, Kafka-driven async stages) is in the source architecture PDF, Section 4, and is out of scope here.

Auth note: per confirmed requirement, the MVP now uses **real login** (not the mock login `Prd.md` originally floated), so a login screen and session handling are in scope below.

---

### 1. Actors

| Actor | What they do in the MVP |
|---|---|
| **Officer** (primary persona) | Logs in, captures/uploads a document + live face, reviews the rule-based verdict and per-module evidence, records the final decision (clear / deny / escalate) |
| **Supervisor/Auditor** (secondary persona) | Logs in, reviews case history and the audit trail; does not perform screenings |
| **SIH evaluators** (demo audience) | Watch the officer flow live; the UI must surface reasoning, not just a verdict |

Both officer and supervisor share the same login screen; role determines which views/actions are available (see Design.md for role-gated UI, Shema.md for the roles column).

---

### 2. High-level flow

```
Login
  │
  ▼
Dashboard (case list)
  │
  ├──► New Screening ──► Capture (doc image + live face burst) ──► POST /screen
  │                                                                     │
  │                                                                     ▼
  │                                                         Pipeline runs synchronously:
  │                                                         OCR/MRZ → Tamper → Deepfake →
  │                                                         3-Way AI Face Verification (Gemini: Live vs Doc vs DB) →
  │                                                         Liveness (MediaPipe) → Watchlist →
  │                                                         Risk Engine (Green/Yellow/Red)
  │                                                                     │
  │                                                                     ▼
  │                                                            Case Result screen
  │                                                            (verdict + per-module evidence)
  │                                                                     │
  │                                                 ┌───────────────────┴───────────────────┐
  │                                                 ▼                                       ▼
  │                                        Green: officer can              Yellow/Red: officer MUST review
  │                                        auto-clear or still                 evidence and record a decision
  │                                        override manually                  (never an automatic denial)
  │                                                 │                                       │
  │                                                 └───────────────► POST /cases/{id}/override
  │                                                                             │
  │                                                                             ▼
  │                                                                 Written to audit log
  │
  └──► Case History (GET /cases) ──► Case Detail (GET /cases/{id}) ──► Audit Trail (GET /audit)
```

---

### 3. Screen-by-screen

**3.1 Login**
- Username/password (real auth — see Shema.md `officers` table).
- On success, role (officer / supervisor / auditor) is attached to the session and drives what's visible next.
- Failed login: generic error, no user enumeration.

**3.2 Dashboard / Case List**
- Table of recent cases: timestamp, traveler/doc reference, verdict (color-coded Green/Yellow/Red), officer, status.
- Backed by `GET /cases`.
- Officer role sees a "New Screening" action; supervisor/auditor role does not.

**3.3 New Screening — Capture**
- Inputs:
  - **Document Capture:** File upload / scanner feed (PNG, JPG, PDF) or preset specimens. The system instantly runs Python rule-based scanning to identify document type (Aadhaar Card, PAN Card, Voter ID, Passport).
  - **Live Face Capture:** Webcam frame burst (12 frames over 1.5s for dynamic liveness + high-res still for 3-way face verification).
  - **Database Cross-Reference:** Optional citizen selector or automatic lookup by extracted document number against the `citizens_registry`.
- Client-side validation only (file present, image readable) — all AI/OCR processing runs server-side.
- Submit → `POST /screen` (synchronous pipeline execution).
- Loading state reflects sequential execution stages: Document Classification ➔ OCR Extraction ➔ Database Reconciliation ➔ Tamper ➔ Deepfake ➔ 3-Way Face Verification ➔ Liveness ➔ Watchlist ➔ Risk Engine.

**3.4 Case Result**
- Verdict banner: Green / Yellow / Red, per Risk Engine output.
- **Document Identification Badge:** Displays detected document type (e.g., `AADHAAR (UIDAI)`, `PAN CARD (INCOME TAX)`, `VOTER ID (ECI)`, `PASSPORT (REPUBLIC OF INDIA)`) with classification confidence.
- **Demographic Database Reconciliation Panel (Core Explainability):**
  - Side-by-side comparison table showing:
    - `Field Name`: Full Name, Date of Birth, Gender, Document ID, Address / Father's Name.
    - `Extracted Value (from Document)`: Value parsed via OCR.
    - `Database Record (from Registry)`: Value retrieved from official `citizens_registry`.
    - `Parity Status`: Green check for exact/fuzzy match, Red alert for discrepancies (e.g., altered DOB or forged name).
- **Per-Module Forensic Panels:**
  - **Tamper Detection:** Tamper score + interactive ELA heatmap residual overlay image.
  - **Deepfake Detection:** Deepfake score & FFT frequency anomaly metrics.
  - **Face Verification (3-Way Multimodal AI):**
    - 3-image visual panel: (1) Cropped Document Photo, (2) Live Webcam Still, (3) Database Registered Record.
    - Pairwise verification chips:
      - Live vs. Document Photo: Validates traveler matches the physical card.
      - Document vs. Database Record: Detects forged/substituted credential photos.
      - Live vs. Database Record: Confirms traveler against the official government registry.
    - Detailed forensic visual reasoning generated by Gemini (jawline, ear contours, eye spacing, aging markers).
  - **Liveness Detection:** Liveness score + live/spoof boolean + blink count & EAR swing graph.
  - **Watchlist Lookup:** Hit boolean, lookout circular category, issuing agency — **must show a "MOCKED DATA" label** (Prd.md §6/7).
- Decision panel: officer selects clear / deny / escalate + free-text reason → `POST /cases/{id}/override`. This step is **mandatory for Yellow/Red**, optional (but always available) for Green — the system can flag, only a human denies (Prd.md §3, source PDF §7 "Human-in-the-loop guarantee").

**3.5 Case Detail (history view)**
- Same layout as Case Result, read-only, reached via `GET /cases/{id}` from the case list.
- Shows the officer's recorded decision + reason alongside the rule-based verdict.

**3.6 Audit Trail**
- Read-only list, `GET /audit`: every automated verdict and every officer decision/override, with timestamp and actor.
- Supervisor/auditor primary screen; officer can view but not edit.

---

### 4. Error / degraded-state flow

Per Techspec §5: any single module failing must not crash the pipeline.
- If a module fails, its panel on the Case Result screen shows **"Inconclusive"** instead of a score, and the case is forced to at least Yellow.
- This should be visually distinct from a genuine Yellow/Red flag (e.g. a module-level "inconclusive" tag vs. a risk-level color) so the officer isn't misled about *why* the case needs review.

---

### 5. Open items affecting this flow
See Tracker.md for the live list. The one directly affecting screens above: exact deepfake model choice may change what confidence/metadata the Deepfake panel can display (some models expose more explainability than others).