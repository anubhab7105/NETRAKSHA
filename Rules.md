# Rules
## Guardrails for Building the MVP

These are the rules anyone (or any AI coding assistant) implementing this project against `Prd.md` / `Techspec.md` / `Shema.md` / `Implementationplan.md` should follow. They exist so scope doesn't silently drift in either direction — neither cutting corners the PRD calls non-negotiable, nor quietly building production-scope infrastructure the sprint doesn't have time for.

---

### 1. Non-negotiable product rules
These come directly from Prd.md and the source architecture PDF and should never be relaxed to save time:

1. **The system can only flag; only a human can deny.** No code path may auto-reject a traveler. Yellow/Red always route to an officer decision (Prd.md §3; source PDF §7 "Human-in-the-loop guarantee").
2. **Every verdict must show why.** No UI or API response may return a bare Green/Yellow/Red without the per-module evidence that produced it (Prd.md §3).
3. **Mocked data must never look real.** The watchlist and citizen registry modules' output must be visibly labeled as mocked everywhere they appear — API response (`is_mocked` field, Schema.md), UI (violet badge, Design.md §1), and any demo narration (Prd.md §6, §7).
4. **A module failure degrades, it never crashes the pipeline.** Any module failing must produce "inconclusive" for that module and force the case to at least Yellow — never a 500 error on `/screen` (Techspec §5).
5. **Demographic mismatches must trigger an explicit risk flag.** If extracted Name, DOB, or Document Number disagrees with the official database record, the case must NEVER auto-clear (Green is forbidden; force at least Yellow or Red with mismatched fields highlighted).

### 2. Scope guardrails (non-goals — do not build these for the MVP)
Per Prd.md §4, explicitly out of scope for this sprint:
- Kubernetes, microservices, Kafka/message queues — single FastAPI process only.
- Real integration with live government registries (UIDAI/NSDL/ECI) — local mocked registry tables only.
- Demographic bias/fairness certification, penetration testing, DPDP compliance sign-off.
- Multi-checkpoint, multi-tenant, HA/failover.

### 3. Scope additions confirmed for this build
- **Storage:** Supabase PostgreSQL (primary, cloud managed with live evaluator app dashboard) + local SQLite async engine (offline fallback).
- **Performance Target:** Sub-2.5 second total screening latency for checkpoint/airport throughput.
- **Auth:** Real login/session handling with bcrypt password hashing and JWT.
- **Document Types:** Multi-document classification and parsing for Indian IDs (Aadhaar, PAN, Voter ID, Passport).
- **Algorithmic Checksums:** Mathematical validation (Verhoeff for Aadhaar, ICAO 9303 for Passport, Regex for PAN).
- **Demographic Verification:** Automatic field-by-field cross-checking against `citizens_registry`.
- **Face Verification:** Google Gemini 1.5/2.0 Flash Multimodal AI for 3-way verification (Live vs Doc vs DB).

### 4. Coding conventions
Per the stack fixed in Techspec.md §2:
- **Backend:** Python, FastAPI. Each of the pipeline modules stays an isolated function/module (not inlined into the route handler) — this is explicitly called out in Techspec §1 as what makes a later move to microservices a lift, not a rewrite.
- **Document Classification:** Rule-based scanning must identify Aadhaar, PAN, Voter ID, or Passport via header keywords, regex structure, and aspect ratio. If classification confidence is low, allow manual override from the officer.
- **Demographic Comparison:** Name comparison must use token-based fuzzy matching (e.g. Levenshtein ratio >= 0.85 tolerance for honorifics/initials). DOB comparison must be strict (day/month/year parity).
- **AI Face Verification:** Face matching uses Google Gemini (1.5/2.0 Flash) Multimodal Vision API via `google-generativeai` with a strict JSON schema prompt for 3-way comparative verification (Live vs Doc vs DB). Network/quota errors must be caught and degraded to `status="inconclusive"`.
- **Checkpoint Latency:** Local CV checks (tamper detection < 0.8s, liveness) must execute concurrently with the Gemini API request via `asyncio` to guarantee sub-2.5s response times.
- **Privacy & Compliance:** The full 12-digit Aadhaar number must be masked on all UI screens as `XXXX-XXXX-1234` in compliance with DPDP Act and UIDAI guidelines.
- **Frontend:** TypeScript, React, Vite, Tailwind. No React Query, WebSocket client, or shadcn/ui — those are production-scope per Techspec §2's comparison table.
- **Data access:** all watchlist lookups go through the `WatchlistProvider` interface (Techspec §3) — never query the mock table directly from route handlers, since that interface is what makes swapping in a real registry later a config change, not a rewrite.
- **Secrets/credentials:** `officers.password_hash` is never plaintext; no password, session token, or raw biometric embeddings appear in logs or the audit log. API keys (e.g. `GEMINI_API_KEY`) and database credentials must be loaded from environment variables (`.env`), never hardcoded in source.

### 5. Definition of done (per case)
A screening case is "done" only when all of the following are true, matching Prd.md §7:
- Verdict + all module results + demographic comparisons are persisted (`module_results`, `extracted_fields`, Schema.md).
- If Yellow/Red, an `officer_actions` row exists before the case can be considered closed.
- An `audit_log` entry exists for the verdict and for any officer action taken.

### 6. When in doubt
If a requirement isn't specified in `Prd.md`, `Techspec.md`, or the source architecture PDF, don't assume a default silently — add it to `Tracker.md` §0 as an open item and flag it, the same way the deepfake-model choice and design palette are tracked there now.