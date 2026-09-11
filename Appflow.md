# App Flow
## Python Rule-Based Fake Identity & Document Screening System — MVP

Scope note: this describes the flow for the MVP build only (single checkpoint, single process, per `PRD.md` / `Techspec.md`). Production-scale flow (multi-checkpoint, WebSocket push, Kafka-driven async stages) is in the source architecture PDF, Section 4, and is out of scope here.

Auth note: the MVP uses **real login** (bcrypt + JWT + supervisor TOTP + forced rotation), not a mock. Throttling (429), step-up tokens, and 403 rotation/MFA gates are part of every flow below.

---

### 1. Actors

| Actor | What they do in the MVP |
|---|---|
| **Officer** (primary persona) | Logs in (rotates password if forced), captures document + 14-frame face burst, reviews verdict + evidence, records `clear`/`escalate` (cannot `deny`) on own cases |
| **Supervisor** (secondary) | Same login + TOTP enrollment; reviews own-unit cases; runs controlled enrollment (create/approve four-eyes, HMAC imports, reconciliation, orphan cleanup); can `clear`/`deny`/`escalate` |
| **Auditor** (secondary) | Read-only: all cases + `GET /api/audit` + verify + access-review + fairness; cannot screen or override |
| **SIH evaluators** (demo audience) | Watch the officer flow live; the UI must surface reasoning, not just a verdict |

Role determines views/actions (see `frontend/src/components/Sidebar.jsx`, `Schema.md` `officers.role/unit`).

---

### 2. High-level flow

```
Login (username/password → JWT or mfa_token → TOTP → session; 403 if rotation/MFA pending)
  │
  ▼
Dashboard / Cases (GET /cases, role-scoped: officer=own, supervisor=unit, auditor=all)
  │
  ├──► New Screening (Scanner: doc webcam + face burst) ──► POST /api/screen (+ Idempotency-Key)
  │                                                                     │
  │                                                                     ▼
  │                                                         Sequential OCR pre-pass (registry hint)
  │                                                         → parallel tamper/physical/deepfake/
  │                                                           local 3-way + Gemini/liveness/watchlist
  │                                                         → demographic reconcile → Risk Engine
  │                                                                     │
  │                                                                     ▼
  │                                                            Case Result (/case/:id)
  │                                                            (verdict + per-module evidence)
  │                                                                     │
  │                                                 ┌───────────────────┴───────────────────┐
  │                                                 ▼                                       ▼
  │                                        Green: officer can              Yellow/Red: stays
  │                                        clear or escalate               pending_review/escalated
  │                                        (never auto-denied)             until officer action
  │                                                 │                       (officer: clear/escalate;
  │                                                 └───────────────► POST /cases/{id}/override + reason
  │                                                                             │  (auditor blocked;
  │                                                                             ▼   version-checked)
  │                                                                 Written to hash-chained audit log
  │
  ├──► Case Detail (GET /cases/{id} + /provenance) — read-only history + decision
  ├──► Registry governance (supervisor): enroll → approve/reject, HMAC import, reconcile, orphan cleanup
  └──► Audit Trail (auditor-only GET /audit + verify + access-review) + Fairness report
```

---

### 3. Screen-by-screen

**3.1 Login (`/login`)**
- Username/password → `POST /auth/login`. Unknown users dummy-verified (generic error, no enumeration); throttled (429).
- Supervisor with TOTP gets `mfa_required` + `mfa_token` and completes `POST /auth/mfa/challenge` (6-digit, drift hint on failure).
- `must_change_password` or unenrolled-supervisor accounts get 403 (`PASSWORD_CHANGE_REQUIRED` / `MFA_SETUP_REQUIRED`) and are routed to `/change-password` (`SecurityGate`) for rotation + TOTP setup/verify.
- On success, `token/role/username` in `localStorage`; 401 (non-step-up) wipes session → `/login`.

**3.2 Dashboard / Case List (`/`)**
- Table: Case ID | Timestamp | DocType | Verdict badge | Status | Action (row → `/case/:id`). Backed by `GET /cases`. Client search is by `#id/doctype` only (no server verdict/date filter in UI).
- Roles: officer+supervisor see Scanner; supervisor+auditor see Audit (officers cannot view audit; auditors cannot scan).

**3.3 New Screening — Capture (`/scan`)**
- Inputs (webcam-only, no file upload/PDF input in UI):
  - **Document Capture:** `WebcamCapture(facingMode=environment)` still.
  - **Live Face Capture:** `WebcamCapture` burst — 14 frames × 150ms (~2.1s after 650ms delay); middle frame sent as `live_capture`, all as `live_frames[]`.
  - No registry citizen selector — lookup is automatic by OCR document-number hint.
- `Idempotency-Key` UUID minted per intent (regenerated when inputs change; sent as header + form fallback). In-flight 409 keeps the key; idempotency-mismatch 422 mints a fresh key.
- Submit → `POST /api/screen` (sequential OCR pre-pass + parallel forensic fan-out + random `challenge_type`). Button shows `Processing...` only (no per-stage telemetry).

**3.4 Case Result (`/case/:id`)**
- Fetches `GET /cases/:id` + `GET /cases/:id/provenance`. Verdict banner: Green / Yellow / Red.
- **Document Header:** type badge (no confidence % in UI) + extracted Document ID (Aadhaar masking `XXXX-XXXX-1234` is spec'd but not implemented — raw values render; see gap).
- **Demographic Reconciliation Panel:** Attribute | Document Extracted | Registry Record | Status (`MATCH`/`MISMATCH`/`UNVERIFIED`; NULL database values when no DB record).
- **Per-Module Forensic Panels:**
  - **Tamper:** score + signed-URL ELA overlay.
  - **Physical forgery:** score + zone overlay (MRZ + PHOTO boxes).
  - **Deepfake:** FFT metrics + anomaly indicator.
  - **Face Verification (hybrid 3-way):** pair chips Live-vs-Doc (primary, local) + Doc-vs-DB + Live-vs-DB; Gemini reasoning callout; simulated cloud shows amber `DEMO ONLY — Simulated AI Excluded` (violet `MOCKED DATA` badge still TODO).
  - **Quality/security zones:** numeric gates (EAR `swing.toFixed(4)`, blur/brightness, zone images where present).
  - **Liveness:** Live/Spoof + blinks + challenge type.
  - **Watchlist:** `HIT`/`CLEAR` chips when not mocked; mocked shows slate notice (violet badge TODO).
- Decision panel: `clear`/`deny`/`escalate` + reason (≥3 chars) → `POST /cases/{id}/override` (+ `If-Match: version`). Rules enforced in UI and API: auditor read-only, officer `deny` disabled (must escalate), `escalated` supervisor-only, 409 on decided/version mismatch. Yellow/Red are never auto-denied; they persist until actioned.

**3.5 Case Detail (history view)**
- Same layout as Case Result, read-only, reached via `GET /cases/{id}` from the case list.
- Shows the officer's recorded decision + reason alongside the verdict, plus provenance block (`verified`, signature, reason).

**3.6 Audit Trail (`/audit`, auditor-only)**
- Read-only list, `GET /audit?limit&offset&actor&entity`: actor, action, entity, timestamp. `GET /audit/verify` chain check; `GET /audit/access-review` registry-access aggregates.
- Officers cannot view audit (403); supervisors can only verify, not list. Auditors can read but not modify.

**3.7 Registry governance (supervisor flows, no dedicated UI docs yet)**
- Enroll (`POST /api/citizens` with photo ≤5MB, checksum-validated) → approve/reject by a different supervisor → live row or secure-delete.
- Authority import (`POST /api/citizens/import` with `X-Import-Signature` HMAC), reconciliation report/run, orphan check/cleanup.

---

### 4. Error / degraded-state flow

Per Techspec §5: any single module failing must not crash the pipeline.
- If a module fails, its panel shows **"Inconclusive"** (or "unavailable…not displayed" for simulated pairs) instead of a score, and the case is forced to at least Yellow.
- This is visually distinct from a genuine Yellow/Red flag (module-level "inconclusive" tag vs. risk-level color) so the officer isn't misled about *why* the case needs review.
- Transport errors: 409 = same key in progress (wait, don't mint a new key); 422 idempotency = mint a fresh key and retry; pipeline exceptions release the claim so same-key retry proceeds.
