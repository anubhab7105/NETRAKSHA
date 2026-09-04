# Design
## Officer Dashboard — UI/UX Spec (MVP)

This covers the frontend described in `Techspec.md` §2 (React + TypeScript + Vite + Tailwind, no React Query/WebSocket/shadcn — those are production-only per the same table) and the screens in `AppFlow.md`.

No specific design reference/brand was provided, so the direction below is a proposed default based on the source PDF's description of the officer dashboard as "data-dense" (§2.2) and the PRD's core UX requirement — evidence and reasoning must be visible, not just a verdict (Prd.md §2, §3). **Flag if you want a different visual direction** — this is an assumption, not a confirmed spec.

---

### 1. Design principles

1. **Evidence over score.** Every verdict is a doorway into per-module evidence, never a bare label. The Case Result screen (AppFlow.md §3.4) is the most important screen in the product — it's what SIH evaluators and officers actually judge.
2. **Color carries meaning, but is never the only signal.** Green/Yellow/Red must be paired with text labels and icons — this is a screening tool used under time pressure, and color-only status is an accessibility and a mis-read risk at a border checkpoint.
3. **Mocked data is never allowed to look real.** The Watchlist panel must be visually distinguishable (badge/label, not just a footnote) from the five real modules, per Prd.md §6.
4. **Dense but scannable.** Officers review many cases; the case list and per-module panels should read as a table/checklist, not marketing-style cards.
5. **The system never implies a final decision.** UI copy avoids words like "denied" or "cleared" for the rule-based verdict itself — those are reserved for the officer's own recorded action. The AI produces a "risk flag," the officer produces a "decision."

---

### 2. Tech constraints (from Techspec.md — do not deviate without updating that doc)
- React + TypeScript + Vite
- Tailwind CSS for styling
- No React Query, no WebSocket client, no shadcn/ui — those are explicitly production-scope (Techspec §2 table). MVP screens are synchronous request/response.
- Frontend build served statically by FastAPI (Techspec §3 deployment row).

### 3. Layout system
- Single main layout: left nav (Dashboard / New Screening / Audit Trail, role-gated per Shema.md `officers.role`), top bar with logged-in officer name + logout.
- Case Result screen: single-column verdict banner at top, then a responsive grid of module evidence panels (2 columns desktop, 1 column narrow).

### 4. Color system (proposed)
| Token | Use |
|---|---|
| Risk Green | Verdict banner + badge for Green cases |
| Risk Yellow | Verdict banner + badge for Yellow cases |
| Risk Red | Verdict banner + badge for Red cases |
| Neutral/Gray | "Inconclusive" module state (distinct from Yellow/Red — see AppFlow.md §4) |
| Accent (mocked-data badge) | A clearly non-risk color (e.g. purple/violet) so it's never confused with Green/Yellow/Red |

Exact hex values aren't specified anywhere in the source docs — pick a Tailwind-default palette (e.g. `emerald`/`amber`/`red`/`slate`/`violet`) unless you want a specific brand palette, in which case tell me and I'll update this.

### 5. Key screens (component-level)

**Login**
- Centered card, username + password, single submit. No "remember me" / SSO — out of scope (real login was requested, but nothing beyond basic auth was specified; see Rules.md for what's in/out of scope on auth).

**Dashboard (Case List)**
- Table: Timestamp | Reference | Verdict badge | Officer | Status.
- Filter/sort by verdict and date at minimum — anything more (search, pagination beyond basic) is a stretch goal, not committed scope.

**New Screening — Capture**
- Capture widgets:
  - Document image uploader with instantaneous classification preview (`Aadhaar`, `PAN`, `Voter ID`, `Passport`).
  - Webcam capture widget (records 12-frame rapid burst for liveness + captures high-res still for face verification).
  - Registry record selector (auto-queries database record matching extracted document number).
- Single "Run Screening" button → stage-by-stage progress telemetry → redirect to Case Result.

**Case Result**
- Verdict banner (full width, color per §4).
- **Document Header:** Document Type Badge (`Aadhaar` [blue], `PAN` [indigo], `Voter ID` [orange], `Passport` [navy]) with confidence percentage and extracted Document ID.
- **Demographic Parity Table:** Full-width card comparing extracted values with official database records:
  - Columns: Attribute | Document Extracted | Registry Record | Status (`MATCH` in emerald / `MISMATCH` in red / `UNVERIFIED` in slate).
  - Highlights specific altered fields (e.g. Forged Date of Birth or Spliced Name).
- **Forensic Evidence Grid:**
  - **Tamper:** Tamper score bar + interactive ELA heatmap residual overlay image.
  - **Deepfake:** FFT spectral peakedness metrics & anomaly indicator.
  - **Face Verification (3-Way Multimodal AI):** 
    - 3-image comparison card: [Document Photo Crop] · [Live Webcam Still] · [Database Registered Photo].
    - Pairwise verification status chips: Live vs Doc, Doc vs DB, Live vs DB.
    - Forensic reasoning callout: Gemini-generated biometric breakdown (ear geometry, jaw structure, eye spacing, aging markers).
  - **Liveness:** Live/Spoof status, detected blinks, EAR swing variance.
  - **Watchlist:** Clear violet **"MOCKED DATA"** badge, lookout circular status, issuing agency.
- Decision panel (sticky footer or bottom card): decision dropdown (Clear / Deny / Escalate) + reason textarea + submit → `POST /cases/{id}/override`.

**Audit Trail**
- Flat, timestamped list: actor, action, entity, timestamp. No editing affordances anywhere on this screen (matches the "auditors can read but not modify" principle in the source PDF §7 — adopted here for the MVP's supervisor/auditor role even though full RBAC is production-scope).

### 6. Explicitly deferred (not in MVP design)
- Real-time WebSocket verdict streaming (source PDF §4 — production only).
- Heatmap/analytics views (source PDF §2.2 "checkpoint-level analytics" — production only).
- Multi-checkpoint switching UI (Prd.md non-goals).