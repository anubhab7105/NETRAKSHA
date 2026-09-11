# Rules
## Guardrails for Building the MVP

These are the rules anyone (or any AI coding assistant) implementing this project against `PRD.md` / `Techspec.md` / `Schema.md` / `Implementationplan.md` should follow. They exist so scope doesn't silently drift in either direction — neither cutting corners the PRD calls non-negotiable, nor quietly building production-scope infrastructure the sprint doesn't have time for.

---

### 1. Non-negotiable product rules
These come directly from PRD.md and the source architecture PDF and should never be relaxed to save time:

1. **The system can only flag; only a human can deny.** No code path may auto-reject a traveler. Yellow/Red always route to an officer decision (PRD.md §3; source PDF §7 "Human-in-the-loop guarantee"). Enforced by RBAC: `officer` role cannot `deny` (must `escalate`), `auditor` is read-only.
2. **Every verdict must show why.** No UI or API response may return a bare Green/Yellow/Red without the per-module evidence that produced it (PRD.md §3).
3. **Mocked data must never look real.** Watchlist output carries `is_mocked=True` (`module_results.is_mocked`); Gemini offline output carries `is_mocked=is_simulated` and drives the `DEMO ONLY` notice. Registry trust uses separate levels (`verified`/`legacy`/`unverified`), not `is_mocked`. UI must keep mocked/simulated visually distinct (violet `MOCKED DATA` badge is still TODO — do not regress to plain chips).
4. **A module failure degrades, it never crashes the pipeline.** Any module failing must produce `status="inconclusive"`, `score=None` + `reason` and force the case to at least Yellow — never a 500 error on `/screen` (Techspec §5). Every `run_*` must wrap in try/except → `inconclusive_result`.
5. **Demographic mismatches must trigger an explicit risk flag.** If extracted Name, DOB, or Document Number disagrees with the official database record, the case must NEVER auto-clear (Green is forbidden; force at least Yellow or Red with mismatched fields highlighted).

### 2. Scope guardrails (non-goals — do not build these for the MVP)
Per PRD.md §4, explicitly out of scope for this sprint:
- Kubernetes, microservices, Kafka/message queues — single FastAPI process only.
- Real integration with live government registries (UIDAI/NSDL/ECI) — local mocked registry tables only.
- Demographic bias/fairness certification, penetration testing, DPDP compliance sign-off (fairness ledger is telemetry only).
- Multi-checkpoint, multi-tenant, HA/failover.

### 3. Scope additions confirmed for this build
- **Storage:** Supabase PostgreSQL (primary) + local SQLite async engine (offline fallback). 10 tables; startup self-heals columns/sequences (no Alembic).
- **Performance Target:** Tamper <1.5s (tested); end-to-end sub-2.5s is aspirational with sequential OCR + 3× local face inference + Gemini. Keep local CV fast and concurrent with Gemini via `asyncio`.
- **Auth:** Real login/session handling with bcrypt (passlib only) + JWT + supervisor TOTP + forced rotation + rate limits + unit scoping.
- **Document Types:** Multi-document classification and parsing for Indian IDs (Aadhaar, PAN, Voter ID, Passport).
- **Algorithmic Checksums:** Mathematical validation (Verhoeff for Aadhaar, ICAO 9303 for Passport, regex for PAN/EPIC).
- **Demographic Verification:** Automatic field-by-field cross-checking against `citizens_registry` (fuzzy name ≥0.85, strict DOB).
- **Face Verification:** Hybrid — local InsightFace `buffalo_l` (authoritative, threshold 0.55) + Google Gemini (`google-genai` SDK, `gemini-3.6-flash`) 3-way reasoning (Live vs Doc vs DB). Simulated cloud never forces Red.

### 4. Coding conventions
Per the stack fixed in Techspec.md §2:
- **Backend:** Python, FastAPI. Each of the pipeline modules stays an isolated function/module (not inlined into the route handler) — this is explicitly called out in Techspec §1 as what makes a later move to microservices a lift, not a rewrite.
- **Document Classification:** Classification lives in `gemini_scanner` profiles + `physical_forgery` aspects/MRZ + `security_zones` templates (no standalone `classifier.py`). If classification confidence is low, allow manual override from the officer.
- **Demographic Comparison:** Name comparison must use token-based fuzzy matching (Levenshtein ratio >= 0.85). DOB comparison must be strict (day/month/year parity).
- **AI Face Verification:** Local InsightFace decides matches; Gemini (`google-genai`, `gemini-3.6-flash`, `response_mime_type=application/json`) provides reasoning. Only `evidence==local` registry mismatches force Red. Network/quota errors must degrade to `status="inconclusive"`.
- **Tamper:** ELA (JPEG q=90) + exact-duplicate SHA1 block-hash copy-move (`COPY_FLOOR=10`, `COPY_SAT=90` as function locals). Do not reintroduce ORB/NCC without updating tests + calibration note.
- **Checkpoint Latency:** Local CV checks must execute concurrently with the Gemini API request via `asyncio` (sequential OCR pre-pass for registry lookup is the only allowed serial step).
- **Privacy & Compliance:** The full 12-digit Aadhaar number must be masked on all UI screens as `XXXX-XXXX-1234` (currently unenforced — new UI must implement it; do not log full Aadhaar). See Tracker gap.
- **Frontend:** JavaScript (JSX), React 19, Vite, Tailwind 4, axios, react-router 7. No TypeScript, no React Query, no WebSocket client, no shadcn/ui.
- **Data access:** all watchlist lookups go through the `WatchlistProvider` interface (Techspec §3) — never query the mock table directly from route handlers. Registry writes go only through dual-approval (`POST /api/citizens` → approve) or HMAC-signed import — never direct inserts from screening.
- **Secrets/credentials:** `officers.password_hash` is bcrypt only (no SHA fallback); no password, session token, or raw biometric embeddings appear in logs or the audit log. API keys and DB credentials come from `.env`, never hardcoded. Naive datetimes only for DB writes (`_utcnow_naive()` — aware datetimes 500 on Postgres).
- **API contracts:** `POST /api/screen` requires `Idempotency-Key` (8–128 chars `[A-Za-z0-9\-_:.]`); reuse on retry. Evidence is authenticated (`/api/evidence/token|view|{filename}`), never publicly mounted. RBAC + optimistic locking (`version`/`If-Match`) on override must be preserved.

### 5. Definition of done (per case)
A screening case is "done" only when all of the following are true, matching PRD.md §7:
- Verdict + all module results + demographic comparisons are persisted (`module_results`, `extracted_fields`, Schema.md).
- If Yellow/Red, the case stays `pending_review`/`escalated` until an `officer_actions` row exists (officers cannot `deny`; escalated cases are supervisor-only).
- An `audit_log` entry exists for the verdict and for any officer action taken (hash-chained; verifiable via `GET /api/audit/verify`).

### 6. When in doubt
If a requirement isn't specified in `PRD.md`, `Techspec.md`, or the source architecture PDF, don't assume a default silently — add it to `Tracker.md` §0 as an open item and flag it, the same way the badge/masking gaps are tracked now.
