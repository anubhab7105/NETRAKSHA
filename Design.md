# Design
## Officer Dashboard — UI/UX Spec (MVP)

This covers the frontend described in `Techspec.md` §2 (React 19 + Vite 8 + Tailwind 4 + axios + react-router 7, **JavaScript/JSX only — no TypeScript**, `oxlint`; no React Query/WebSocket/shadcn — those are production-only per the same table) and the screens in `Appflow.md`.

No specific design reference/brand was provided, so the direction below is a proposed default based on the source PDF's description of the officer dashboard as "data-dense" (§2.2) and the PRD's core UX requirement — evidence and reasoning must be visible, not just a verdict (PRD.md §2, §3). **Flag if you want a different visual direction** — this is an assumption, not a confirmed spec.

---

### 1. Design principles

1. **Evidence over score.** Every verdict is a doorway into per-module evidence, never a bare label. The Case Result screen (Appflow.md §3.4) is the most important screen in the product — it's what SIH evaluators and officers actually judge.
2. **Color carries meaning, but is never the only signal.** Green/Yellow/Red must be paired with text labels and icons — this is a screening tool used under time pressure, and color-only status is an accessibility and a mis-read risk at a border checkpoint.
3. **Mocked data is never allowed to look real.** Watchlist (`is_mocked=True`) and simulated Gemini (`is_simulated`) must be visually distinguishable (violet badge/label, not just a footnote). **Gap:** currently amber `DEMO ONLY` box (Gemini) and slate notice + HIT/CLEAR chips (watchlist) — no violet `MOCKED DATA` string exists in `frontend/src`. Do not ship new mocked surfaces without the badge.
4. **Dense but scannable.** Officers review many cases; the case list and per-module panels should read as a table/checklist, not marketing-style cards.
5. **The system never implies a final decision.** UI copy avoids words like "denied" or "cleared" for the verdict itself — those are reserved for the officer's own recorded action. The AI produces a "risk flag," the officer produces a "decision."
6. **PII masking is mandatory.** Aadhaar must render as `XXXX-XXXX-1234`. **Gap:** `CaseReport.jsx` renders extracted/database values raw — new work must add masking (see Tracker).

---

### 2. Tech constraints (from Techspec.md — do not deviate without updating that doc)
- React 19 + Vite 8 (JS/JSX, no `*.ts/*.tsx`, no `tsconfig`)
- Tailwind 4 via `@tailwindcss/postcss` + `postcss` (`@import "tailwindcss"`, `@theme` tokens)
- axios singleton (`src/api.js`); `DEV` and `:8000` use same-origin `/api` via Vite proxy; `VITE_API_BASE_URL` must end with `/api`
- No React Query, no WebSocket client, no shadcn/ui — MVP screens are synchronous request/response.
- Frontend build served statically by FastAPI from `frontend/dist` (SPA fallback, must stay last route); `sourcemap:false` intentional; Vercel rewrites `/(.*)→/index.html`.
- Lint is `oxlint` (`npm run lint`); no ESLint.

### 3. Layout system
- Single main layout: Sidebar nav (Cases / Scanner / Audit — role-gated: officer+supervisor=Scanner, supervisor+auditor=Audit) + ambient blobs, top bar with logged-in officer name + logout. `SecurityGate` forces `/change-password` when `must_change_password`/`mfa_setup_required`.
- Case Result screen: single-column verdict banner at top, then a responsive grid of module evidence panels (2 columns desktop, 1 column narrow).
- Routes (`src/App.jsx`, lazy): `/login` (public), `/change-password` (authed), `/` Dashboard, `/scan` Scanner, `/case/:id` CaseReport, `/audit` AuditTrail, `*` NotFound.

### 4. Color system (proposed)
| Token | Use |
|---|---|
| Risk Green | Verdict banner + badge for Green cases |
| Risk Yellow | Verdict banner + badge for Yellow cases |
| Risk Red | Verdict banner + badge for Red cases |
| Neutral/Gray | "Inconclusive" module state (distinct from Yellow/Red — see Appflow.md §4) |
| Accent (mocked-data badge) | A clearly non-risk color (e.g. purple/violet) so it's never confused with Green/Yellow/Red — **not yet implemented** |

Exact hex values aren't specified anywhere in the source docs — pick a Tailwind-default palette (e.g. `emerald`/`amber`/`red`/`slate`/`violet`) unless you want a specific brand palette, in which case tell me and I'll update this.

### 5. Key screens (component-level, as built)

**Login (`views/Login.jsx`)**
- Centered card, username + password. Supervisor TOTP step-up stays on-page (6-digit numeric input → `POST /auth/mfa/challenge`). Throttle/drift errors shown inline; 401 (non-step-up) wipes session.

**Security setup (`views/SecuritySetup.jsx`)**
- Forced-rotation form (`POST /auth/change-password`, min-10-chars / 3-of-4-classes hint) + supervisor-only MFA section (`setup` → QR/manual key → `verify`).

**Dashboard / Case List (`views/Dashboard.jsx`)**
- Table: Case ID | Timestamp | DocType | Verdict badge | Status | Action. Client search by `#id/doctype` only — no verdict/date filter, no Officer column.

**New Screening — Capture (`views/Scanner.jsx`)**
- Webcam-only widgets (no file upload): document (`environment`) + face burst (`user`, 14 frames × 150ms after 650ms delay; middle frame = `live_capture`).
- UUID `Idempotency-Key` per intent (header + form fallback; regenerated on input change). Single "Initiate Screening" button (disabled without doc) → `Processing...` → redirect to Case Result. No per-stage telemetry, no registry selector.

**Case Result (`views/CaseReport.jsx`)**
- Verdict banner (full width, color per §4).
- **Document Header:** type badge (no confidence %) + extracted Document ID (masking TODO).
- **Demographic Parity Table:** Attribute | Document Extracted | Registry Record | Status (`MATCH`/`MISMATCH`/`UNVERIFIED`).
- **Forensic Evidence Grid (signed evidence URLs via `api.defaults.baseURL` — note `EvidenceImage` hardcodes `/api/...`, breaks on absolute `VITE_API_BASE_URL`; fix to use baseURL):**
  - **Tamper:** score bar + ELA overlay.
  - **Physical forgery:** score + zone overlay.
  - **Face Verification (hybrid 3-way):** pair chips Live-vs-Doc / Doc-vs-DB / Live-vs-DB + Gemini reasoning; no 3-image strip; simulated pairs show notice, not badge (TODO).
  - **Deepfake / Liveness / Checksum / Zones:** numeric FFT/EAR (`swing.toFixed(4)`) / checksum / zone panels.
  - **Watchlist:** HIT/CLEAR chips or slate "registry not connected" notice (violet badge TODO).
- Decision panel: action buttons (Clear / Deny / Escalate) + reason textarea (≥3 chars) → `POST /cases/{id}/override` (+ `If-Match`). Officer `deny` disabled; auditor read-only; `escalated` supervisor-only.

**Audit Trail (`views/AuditTrail.jsx`)**
- Flat, timestamped list (`GET /audit?limit&offset&actor&entity`) + `GET /audit/verify` chain check (note: duplicated `handleVerify` — second shadows first; dedupe). No editing affordances (auditor-only list; supervisor verify-only).

### 6. SEO / site config (fix before release)
- `VITE_SITE_URL` is the intended single source (`vite.config.js` `seoFiles()` rewrites `%SITE_URL%` in `index.html` and emits `robots.txt/sitemap.xml/llms.txt`). Bugs: three defaults disagree (`vite.config  https://netraksha.xyz` vs `config/site.js https://www.netraksha.xyz` vs `.env.example https://sih-weld-psi.vercel.app`); `OG_IMAGE` points to `og-image.jpeg` but the asset is `og-image.png`; `public/robots.txt|sitemap.xml|llms.txt` contain literal `%SITE_URL%`/`%API_URL%` (Vite only rewrites `index.html`, copies the rest verbatim); `public/404.html` hardcodes `netraksha.xyz` and is dead on Vercel.

### 7. Explicitly deferred (not in MVP design)
- Real-time WebSocket verdict streaming (source PDF §4 — production only).
- Heatmap/analytics views (source PDF §2.2 "checkpoint-level analytics" — production only).
- Multi-checkpoint switching UI (PRD non-goals).
