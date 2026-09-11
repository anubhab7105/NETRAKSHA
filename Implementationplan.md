# Implementation Plan
## MVP — ~6-Day Sprint (completed — reference)

Confirmed for this build: **CPU-only** (no GPU/`nvidia-smi` on dev box; InsightFace falls back to `CPUExecutionProvider`), **~6 days**, specimens **shipped** (see Day 1), storage is **dual-engine** (Supabase PostgreSQL primary + SQLite fallback), and the officer dashboard uses **real login** (bcrypt + JWT + supervisor TOTP + rotation). Each day below reflects those confirmations. Status reflects the code as built — see `Tracker.md` for remaining gaps.

---

### Day 1 — Foundations, Database & Specimen Registries — done
- FastAPI single-process skeleton with canonical `/api/*` endpoints (plus bare legacy aliases): `auth/login|logout|mfa/*|change-password`, `screen` (idempotent), `cases`, `cases/{id}`, `cases/{id}/override`, `cases/{id}/provenance`, `audit(+/verify|access-review)`, `fairness/report`, `citizens*` (search/enroll/approve/reject/import/reconcile/orphans), `evidence/*`, `health`, SPA fallback.
- Database (PostgreSQL/SQLite dual async engine) + 10 tables (`officers`, `citizens_registry`, `registry_enrollments`, `screening_cases`, `extracted_fields`, `module_results`, `officer_actions`, `audit_log`, `screening_idempotency`, `watchlist_entries`) with startup self-healing (no Alembic).
- Seed citizen records: Aadhaar, PAN, Voter ID, Passport + `L898902C3 / Jasmine Specimen` matching `samples/genuine_doc.png`; watchlist mocks; officers `officer1/supervisor1/auditor1` (+`officer2/BORDER_UNIT_2`), all `must_change_password=True`.
- `officers` table + real auth (passlib bcrypt, JWT `purpose=session`, TOTP, 5/300s throttles, unit scoping).
- React 19 + Vite + Tailwind 4 (JS/JSX, oxlint) shell with login, `SecurityGate`, role-gated nav.

### Day 2 — OCR, Demographic Verification, Tamper & Physical — done
- Local OCR pre-pass: Tesseract (`--psm 6`) + PassportEye + regex + ICAO checks; Gemini `gemini-3.6-flash` (`google-genai`) classifier/OCR with offline simulation.
- Checksums: Verhoeff (Aadhaar), ICAO (7,3,1) (Passport), PAN/EPIC regex.
- Demographic cross-verification vs `citizens_registry` (fuzzy name ≥0.85, strict DOB/ID, address ≥0.60) + trust levels.
- Tamper: ELA (JPEG q=90) + exact-duplicate SHA1 block-hash copy-move + JET overlay (tested <1.5s; docstring still says ORB — fix comment).
- Physical forgery: layout/MRZ-font/photo-frame/moiré/QR/guilloche inventory + overlay (tested <5s).
- Wired into `/screen` with fault isolation (`inconclusive`, never crash) + `Idempotency-Key`.
- Frontend: Scanner (webcam-only, 14-frame burst) + Demographic table (masking still TODO).

### Day 3 — Hybrid Face Verification + Liveness — done
- Local authoritative: InsightFace `buffalo_l` 1:1 + 3-way (all pairs with both inputs; threshold 0.55, band 0.45–0.65; quality gates; CPU). Cloud: Gemini 3-way reasoning + `photo_tamper_anomaly`. Fusion: local decides; only `evidence==local` DB mismatches force Red; simulated cloud excluded.
- Liveness: MediaPipe `face_landmarker.task` EAR + motion + moiré + yaw/mouth; randomized `blink/head_turn/mouth_open`; `MIN_BURST=3`, threshold 0.45.
- Frontend: face burst widget + pair chips + liveness panel (EAR numeric; no EAR graph, no 3-image strip).

### Day 4 — Deepfake + Watchlist (mocked) + Risk Engine — done
- Deepfake: FFT heuristic (`0.5*hf+0.3*peak+0.2*rolloff`, `classifier_integrated=False`).
- Watchlist: `MockWatchlistProvider` (5 fictional entries) behind `WatchlistProvider` — `is_mocked=True` set; violet badge still TODO.
- Risk Engine: mean + floors → Green (<0.35)/Yellow (<0.65)/Red; hard flags: demographic critical / watchlist / local face → Red; unverified trust / demo-unavailable / recapture → ≥Yellow; liveness fail / any inconclusive / deepfake ≥0.7 → ≥Yellow.
- Frontend: deepfake/watchlist panels, verdict banner, RBAC decision panel (`POST /cases/{id}/override`, optimistic locking).

### Day 5 — Integration testing + audit trail + case history — done
- `tests/` covers PRD §7 (genuine → Green; DOB forgery → Red/Yellow; copy-move → Red/Yellow + ELA; imposter → Red local; watchlist → Red mocked; tamper <1.5s) plus auth/quality/physical/three-way suites: `pytest tests/ -v`.
- `GET /cases`, `GET /cases/{id}(+ /provenance)`, `GET /audit(+/verify|access-review)`, `GET /fairness/report`, citizens governance, signed evidence.
- Dashboard / Case Detail / Audit Trail screens (auditor-only audit list; supervisor verify-only).

### Day 6 — Hardening, demo rehearsal, buffer — done, gaps tracked
- Fault isolation verified per module (bad path, blank image, empty burst) in tests.
- Demo run-through per PRD §7 timed (`total_latency_ms` measured; sub-2.5s aspirational).
- Remaining gaps moved to `Tracker.md` §0b: violet badge, Aadhaar masking, SEO/SITE_URL + `EvidenceImage` baseURL + duplicated `handleVerify` fixes, tamper docstring, `__init__` exports, Aadhaar/PAN/Voter specimens.

---

### Explicitly out of this plan (PRD.md §4 non-goals)
Kubernetes/microservices/Kafka, real national DB/watchlist integration, demographic bias/fairness certification, penetration testing, DPDP sign-off, multi-checkpoint/multi-tenant/HA. See the source architecture PDF §11 for where these land in the post-hackathon roadmap.
