# Project Audit Against PRD.md

Audit target: Python Rule-Based Fake Identity & Document Screening System MVP, checked against `PRD.md` plus `Techspec.md`, `Appflow.md`, `Rules.md`, `Schema.md`, and the current backend/frontend/pipeline implementation.

Scope note: this audit is intentionally defect-first. It lists concrete PRD or supporting-spec gaps that affect correctness, security, demo readiness, auditability, or explainability. No code changes were made.

## Findings

`[P1] Screenings can bypass authentication and officer attribution — backend/app.py:306`

`POST /api/screen` silently assigns `officer_id = 1` when auth is missing or invalid, and `POST /api/cases/{id}/override` similarly falls back to `officer1` at `backend/app.py:625`. This breaks the PRD's human-in-the-loop/audit premise because unauthenticated requests can create screening cases and record final officer actions attributed to a real seeded officer. It also weakens the audit trail: the log records an actor, but the actor may not be the person who actually made the request. The fix is to require a valid bearer token for screening and override, then separately enforce role permissions.

`[P1] Case history and audit data are exposed without authentication — backend/app.py:519`

`GET /api/cases`, `GET /api/cases/{id}`, and `GET /api/audit` are public route handlers with no auth dependency (`backend/app.py:519`, `backend/app.py:551`, `backend/app.py:669`). These endpoints return screening cases, extracted demographic fields, module outputs, officer actions, and audit logs. That contradicts the PRD's security-sensitive border-screening context and the app-flow requirement that officers/supervisors/auditors log in before viewing dashboard, case detail, or audit trail. Require authentication on all case and audit endpoints, then gate access by role.

`[P1] The production screening path never runs the liveness module — backend/app.py:415`

The PRD requires live webcam frame-burst liveness before risk verdicts, and `pipeline/liveness.py` implements that module, but `/api/screen` never imports or calls `run_liveness`. The risk engine call at `backend/app.py:415` omits `liveness_live`, `liveness_score`, and `liveness_status`, so a static-photo or replay attack cannot force Yellow in real screenings. The frontend also uploads only one optional image as `live_capture` (`frontend/src/views/Scanner.jsx:24`) rather than the required 12-frame burst. Wire a burst input through the API, run `run_liveness`, persist its `module_results` row, and pass the result into `assess_risk`.

`[P1] 3-way face verification never receives the database reference photo — backend/app.py:361`

The PRD's face module is explicitly 3-way: live capture vs document photo vs database reference photo. The backend calls `scan_document(str(doc_path), live_str, None)` before the citizen registry lookup, so Gemini never receives a DB photo and `doc_vs_db_match` / `live_vs_db_match` are null in normal scans. The later DB lookup at `backend/app.py:387` retrieves `CitizenRegistry.photo_uri`, but it is too late to affect the face-verification call. Resolve the citizen record/photo before the Gemini call, or split classification/OCR from face verification so the DB reference can be included.

`[P1] Gemini/API failures fabricate successful evidence instead of degrading to inconclusive — pipeline/gemini_scanner.py:129`

When the Gemini API key is missing or the call fails, `scan_document` falls back to `_simulate_scan`, marks `is_simulated = True`, and returns high-confidence demographics and face matches. `_simulate_scan` even chooses a random document profile at `pipeline/gemini_scanner.py:268`. The backend then persists this as `module_name="gemini_ai"` with `status="ok"` at `backend/app.py:464`, allowing simulated rule-based output to contribute to Green cases. This violates the rule that module failure must degrade to `status="inconclusive"` and force at least Yellow. Keep simulation only behind an explicit demo mode, and treat real API failure/missing key as an inconclusive module result.

`[P1] Multi-document OCR/classification is not implemented as specified in the real pipeline — backend/app.py:344`

The PRD calls for rule-based document classification plus specialized parsers for Aadhaar, PAN, Voter ID, and Passport. The actual `/api/screen` flow imports `scan_document` from `pipeline/gemini_scanner.py` and does not call `pipeline/ocr_mrz.py` at all. The local OCR module's `VISIBLE_FIELDS` are passport-style fields only (`pipeline/ocr_mrz.py:44`), while Aadhaar/PAN/Voter extraction exists only as Gemini prompt output or offline simulation profiles. This makes the core multi-document support fragile and non-deterministic, and it prevents the system from demonstrating local parser behavior promised by the PRD. Add a real document classifier plus per-document extraction modules, and reserve Gemini for the specific AI-assisted tasks the spec assigns to it.

`[P2] Deepfake detection is run on the uploaded document instead of a face image — backend/app.py:356`

`run_deepfake` is documented to analyze a face image/frame, but `/api/screen` passes `str(doc_path)`. For identity documents this means the FFT heuristic is measuring the whole card/page, not the live face or cropped document portrait, so the deepfake score is not evidence for the PRD's synthetic-face/deepfake check. Run deepfake analysis against the live capture and/or extracted face crop, and persist which image was analyzed.

`[P2] Watchlist data is seeded into the database but the screening path ignores it — pipeline/watchlist.py:95`

`backend/seed.py` inserts `WatchlistEntry` rows, but `check_watchlist` uses a process-local hard-coded `MockWatchlistProvider` list (`pipeline/watchlist.py:95`) and `/api/screen` calls that provider directly (`backend/app.py:409`). Changes to the SQLite/Postgres `watchlist_entries` table will not affect screening results, and the database-backed mock registry described in `Schema.md` is not actually the source of truth. Implement a DB-backed `WatchlistProvider` for the MVP seed table while preserving the provider abstraction.

`[P2] The frontend has no audit trail screen or route — frontend/src/App.jsx:33`

The app flow requires an Audit Trail screen backed by `GET /audit`, and the backend exposes `/api/audit`, but the React router only defines dashboard, scanner, and case report routes (`frontend/src/App.jsx:33` to `frontend/src/App.jsx:35`). The sidebar likewise offers only Case Dashboard and Kiosk Scanner (`frontend/src/components/Sidebar.jsx:35` and `frontend/src/components/Sidebar.jsx:43`). Supervisors/auditors therefore cannot use the audit feature the PRD lists as a success criterion. Add an audit route/view and role-appropriate navigation.

`[P2] Supervisor/auditor role gating is only cosmetic and still exposes scanner navigation — frontend/src/components/Sidebar.jsx:43`

`Sidebar` reads the user's role (`frontend/src/components/Sidebar.jsx:8`) but does not use it to hide officer-only actions, and `/scan` is always routable via `ProtectedRoute` if any token is present (`frontend/src/App.jsx:34`). This contradicts `Appflow.md`, where officer role sees New Screening and supervisor/auditor roles do not. Enforce role checks in both frontend routing/navigation and backend endpoints.

`[P2] Case results do not show all module evidence required to explain verdicts — frontend/src/views/CaseReport.jsx:82`

The case report extracts only `gemini_ai`, `tamper`, and `watchlist` modules (`frontend/src/views/CaseReport.jsx:82` to `frontend/src/views/CaseReport.jsx:84`). It does not render deepfake output, checksum validation, liveness evidence, classification confidence, inconclusive states, or a complete module summary. That undercuts the PRD's "every verdict must show why" requirement and makes Yellow/Red cases hard to explain to SIH evaluators. Render every persisted module result with status, score, raw evidence, and any evidence URI, including inconclusive modules.

`[P2] The watchlist mocked-data badge only appears on hits, and registry mock status is not surfaced — frontend/src/views/CaseReport.jsx:212`

The PRD requires mocked data to be clearly labeled wherever it appears. The watchlist panel is rendered only when `watchlistModule.raw_output.is_hit` is true (`frontend/src/views/CaseReport.jsx:212`), so a clear watchlist lookup can disappear entirely along with its mocked-data status. The citizen registry demographic panel also compares against seeded/mock records but has no mocked-data badge. Always show watchlist lookup status and mark both watchlist and citizen-registry outputs as mocked in the UI/API evidence.

`[P2] Risk recommendations use final-action language reserved for officers — pipeline/risk_engine.py:80`

The PRD says the system can only flag and only a human can deny. The risk engine returns instructions such as "Detain and escalate to supervisor immediately" (`pipeline/risk_engine.py:80`), and the verdict banner repeats "Detain and escalate" for Red cases (`frontend/src/views/CaseReport.jsx:27`). That copy can be read as an automated operational decision rather than an rule-based risk flag. Reword rule-based output as review/escalation recommendations and keep detention/denial language inside the officer action workflow.

`[P3] Default credentials and weak crypto fallbacks are present in the demo path — backend/app.py:63`

The app uses a hard-coded fallback JWT secret (`backend/app.py:63`) and falls back to unsalted SHA-256 password hashes if `passlib` is unavailable (`backend/seed.py:44`, `backend/app.py:122`). The PRD allows MVP simplification but also requires real login and no hardcoded secrets. Fail startup when `JWT_SECRET` is absent outside explicit local-demo mode, and remove the SHA-256 password fallback or make it impossible in the shipped demo configuration.

`[P3] Test coverage is module-heavy but misses the integrated API/UI success criteria — tests/test_pipeline.py:1`

The test suite exercises many individual pipeline helpers, but it does not cover authenticated `/api/screen`, unauthenticated rejection, liveness wiring, DB-photo 3-way face verification, case persistence shape, `/api/audit`, role gating, or frontend evidence rendering. Those are exactly where most PRD gaps currently live. Add FastAPI integration tests and at least smoke-level frontend tests around the five PRD demo scenarios.

## Verification

- Read requested `review-agent` skill instructions from `C:\Users\ANKUSH DAS\.codex\skills\.system\review-agent\SKILL.md`.
- No `AGENTS.md` file exists in the repository.
- Reviewed `PRD.md`, `Techspec.md`, `Rules.md`, `Appflow.md`, `Design.md`, `Schema.md`, `Implementationplan.md`, `Tracker.md`, backend routes/models/seed/database, pipeline modules, tests, and frontend routes/views/components.
- Attempted to run `python -m pytest tests/ -v`; the system `python` command is not on PATH.
- Attempted to run `py -3 -m pytest tests/ -v`; no installed Python was found through `py`.
- Attempted to run bundled Python at `C:\Users\ANKUSH DAS\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/ -v`; it failed because `pytest` is not installed in that runtime.

## Overall Assessment

The repository has a useful skeleton: FastAPI routes, SQLAlchemy models, seed data, several local CV modules, a risk engine, and a React dashboard shell. However, the current application is not yet PRD-complete for the MVP demo. The largest blockers are authentication bypasses, missing liveness in the real screening path, incomplete 3-way face verification, simulated Gemini output being treated as successful evidence, and incomplete frontend explainability/audit surfaces.

The highest-value next pass should be integration-first: secure all case/audit endpoints, wire the missing modules into `/api/screen`, persist every module result with honest `ok`/`inconclusive` status, and update the case report to render the full evidence set.
