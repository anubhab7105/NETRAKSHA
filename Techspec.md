# Technical Specification
## MVP Architecture

### 1. Architecture overview
Single-process FastAPI backend (matches the original hackathon prototype's shape, per the source doc), with each pipeline module implemented as an isolated Python module/function so it can later be lifted into its own microservice without a rewrite — this mirrors the "prototype vs production" migration path in the source architecture doc.

Request flow (as built — sequential OCR pre-pass + parallel forensic fan-out):
```
Frontend (React 19 JS + Vite, axios sync request/response)
   → POST /api/screen  (document_image* + live_capture? + live_frames[]? + Idempotency-Key*)
      → 0. OCR pre-pass (sequential, run_in_executor): Tesseract + PassportEye → registry lookup hint
      → parallel asyncio.gather (run_in_executor) of:
        → 1. Checksums: Verhoeff / ICAO 9303 / PAN / EPIC regex
        → 2. Demographic cross-check vs citizens_registry (fuzzy name ≥0.85, strict DOB)
        → 3. Tamper: ELA + exact-duplicate SHA1 copy-move (<1.5s tested)
        → 4. Physical forgery: layout / MRZ-font / photo-frame / moiré / QR (<5s tested)
        → 5. Deepfake: FFT radial spectrum heuristic
        → 6. Face (hybrid): InsightFace buffalo_l local 1:1 + 3-way (authoritative) ∥ Gemini cloud reasoning
        → 7. Liveness: MediaPipe EAR + motion + moiré (challenges blink/head_turn/mouth_open)
        → 8. Watchlist: MockWatchlistProvider (is_mocked=True)
      → 9. Risk Engine: mean + hard-flag floors → Green / Yellow / Red
   → response: verdict + per-module evidence + demographic pairs + provenance + latency
   → written to database (screening_cases + extracted_fields + module_results + audit_log + screening_idempotency)
```

No message queue, no separate services — every module runs as an isolated function call within one request for the demo. No timeout/cancellation on the gather; local 3-way runs 3× InsightFace serially inside one worker.

### 2. Tech stack — MVP vs. production
| Layer | MVP (this build) | Production (source doc, future) |
|---|---|---|
| Backend | Python 3.11, FastAPI, single process | Python microservices behind Kong/API Gateway, gRPC internally |
| Frontend | React 19 + Vite 8 + Tailwind 4 + axios + react-router 7 (JS/JSX, oxlint). No TypeScript | Same, + React Query, WebSocket, shadcn/ui |
| Storage | Supabase PostgreSQL (`postgresql+asyncpg://`) / SQLite async fallback (`sqlite+aiosqlite:///screening.db`); 10 tables; startup self-heal, no Alembic | PostgreSQL, encrypted object storage, Redis, immutable audit log store |
| Messaging | None (direct function calls + asyncio fan-out) | Apache Kafka / RabbitMQ |
| OCR & Extraction | Local Tesseract + PassportEye + regex plus Gemini `gemini-3.6-flash` (`google-genai` SDK) classifier/OCR with offline simulation; Verhoeff / ICAO 9303 / PAN / EPIC post-checks | Fine-tuned PaddleOCR / TrOCR + ICAO 9303 parser |
| Demographic Verification | In-memory + DB reconciliation (token-sort Levenshtein name ≥0.85, addr ≥0.60, strict DOB/ID) + trust levels (verified/legacy/unverified) | Real-time secure API integration with UIDAI, NSDL, ECI, and Passport Seva |
| Face verification | Hybrid: InsightFace `buffalo_l` local (ArcFace cosine, 0.55, CPU) authoritative + Gemini cloud reasoning; simulated cloud excluded from verdict | Dedicated sovereign vision microservice / Triton / ONNX + secure registry feeds |
| Tamper detection | ELA (JPEG q=90) + exact-duplicate SHA1 block-hash copy-move (tested <1.5s) | Trained CNN ensemble + classical checks |
| Physical forgery | Layout/font/frame/moiré/QR/guilloche inventory (tested <5s) | Trained CNN ensemble + classical checks |
| Deepfake detection | FFT frequency-artifact heuristic (spectral peakedness) | Dedicated trained GAN/diffusion-artifact classifier |
| Liveness | EAR + motion + moiré, randomized challenge (MediaPipe `face_landmarker.task`) | Depth/texture anti-spoof CNN or certified SDK |
| Watchlist/DB | Mocked local table (`WatchlistProvider`, `is_mocked=True`) | Secure mTLS integration with national registries |
| Registry governance | Dual-approval queue (four-eyes) + HMAC authority import + reconciliation + orphan cleanup | Same hardened + HSM |
| Audit/provenance | Hash-chained audit (`/audit/verify`), signed provenance (HMAC-SHA256), fairness ledger | Immutable store + third-party audit |
| Deployment | `uvicorn` locally, frontend `dist` served by FastAPI; Vercel SPA + Render API | Docker + Kubernetes, govt cloud/on-prem, Terraform, CI/CD |

CPU-only on dev box (no GPU/`nvidia-smi`); `onnxruntime.get_available_providers()` falls back to `CPUExecutionProvider`. Tesseract is a system install (no vendored binary shipped).

### 3. Module specs (MVP, as built)
For each: input → processing → output. All return `ModuleResult(status=ok|inconclusive, score|None, raw_output, evidence_uri)` and never raise.

**OCR, Demographic Extraction & Checksums** — Input: document image. Local `run_ocr_mrz` (Tesseract `--psm 6` + PassportEye + ICAO `check_digit`) plus Gemini structured JSON; post-validated:
- *Aadhaar:* 12th-digit Verhoeff.
- *Passport:* ICAO 9303 modulus-10 (7,3,1) across number/DOB/expiry/composite.
- *PAN:* `^[A-Z]{5}[0-9]{4}[A-Z]$`. *EPIC:* `^[A-Z]{3}[0-9]{7}$`.
Output: `{fields, checksum_valid, raw_text}` + `extracted_fields` rows.

**Database Demographic Cross-Verification** — Input: extracted fields + `citizens_registry` row (auto-lookup by OCR document-number hint, no citizen-ID param). Checks name fuzzy, strict DOB, address similarity + PIN, exact doc ID. Output: `{matched, discrepancy_count, field_comparisons[], db_record, trust:{level}}`. Unverified trust floors at Yellow.

**Tamper detection** — Input: document image. ELA residual + SHA1 exact-duplicate block matching (`bs=8,stride=8,min_dist=140,min_std=10,|dy|≥2`; `score=0.60*copy+0.40*ela`; `COPY_FLOOR=10,COPY_SAT=90` locals). Output: `{tamper_score 0-1, evidence_image_uri (JET overlay)}`.

**Physical forgery** — Input: document image + classified type. Six weighted checks (0.22/0.16/0.22/0.20/0.10/0.10): layout aspect, MRZ monospace lattice, photo-boundary quad, print-scan moiré FFT + acutance, QR/barcode, guilloche FFT + hologram inventory (`not_verifiable`). Output: `{physical_score, evidence overlay}`.

**Deepfake detection** — Input: face image/frame. FFT radial power spectrum (`0.5*hf+0.3*peak+0.2*rolloff`). Output: `{deepfake_score 0-1, method=fft_frequency_artifact_heuristic, classifier_integrated=False}`.

**Face verification (hybrid 3-way)** — Input: doc photo + live still + DB reference. Local InsightFace computes every pair with both inputs (`engine=insightface_local`, largest-face + 1.8×/1.6× retry, face_quality gates, Haar only for side-angle explanation). Cloud Gemini returns reasoning + `photo_tamper_anomaly`. Fusion: local Live-vs-Doc primary (Gemini fallback with agree/disagree provenance); only `evidence==local` Doc/Live-vs-DB mismatches force Red. Output: `{pairs{live_vs_doc,doc_vs_db,live_vs_db:{match,similarity,engine}}, completeness, visual_reasoning}`.

**Liveness** — Input: frame burst (≥3 frames; app sends 14). MediaPipe FaceLandmarker (IMAGE, 1 face) 468-pt EAR (`LIVE_THRESHOLD=0.45`) + motion + screen-moiré + yaw/mouth; randomized `challenge_type`. Output: `{liveness_score 0-1, live: bool, blink_count, challenge}`.

**Document/face quality** — `document_quality` (MIN_DIM=600, blur 50, dark 40, bright 220) and `face_quality` (sharpness/brightness/contrast/size/yaw/occlusion) gate or warn; failures surface as `FACE_QUALITY_RECAPTURE`/Yellow by design.

**Watchlist lookup** — Input: extracted name/ID. `MockWatchlistProvider` (5 fictional entries; exact ID + token-overlap ≥0.5 fuzzy name). Output: `{hit, matched_entry?, is_mocked=True}`.

**Risk engine** — Input: all module outputs. Mean of risk components + `_escalate` floors → Green (<0.35) / Yellow (<0.65) / Red. Hard flags:
- *Demographic critical mismatch:* forces **RED**.
- *Watchlist hit:* forces **RED**.
- *Local face mismatch (incl. evidence==local DB pairs):* forces **RED**.
- *Unverified registry trust / demo-cloud-unavailable / recapture-needed:* floors at **YELLOW**.
- *Liveness failure:* forces at least **YELLOW**.
- *Any inconclusive (tamper/physical/deepfake/face/liveness, incl. deepfake ≥0.7 as Yellow):* forces at least **YELLOW**.

### 4. API design (canonical `/api/*`; bare aliases kept for compat)
| Endpoint | Method | Purpose |
|---|---|---|
| `/api/auth/login` | POST | Username/password → JWT (`purpose=session`) or `mfa_token`; 429-throttled, dummy-verified |
| `/api/auth/mfa/challenge` | POST | `{mfa_token,code}` → session (supervisor step-up) |
| `/api/auth/mfa/setup\|verify\|disable` | POST | Supervisor TOTP enrollment lifecycle (QR + manual key) |
| `/api/auth/change-password` | POST | Rotation (clears `must_change_password`, sets `password_changed_at`) |
| `/api/auth/logout` | POST | Audit-only (JWT stateless; always 200) |
| `/api/screen` | POST | Multipart `document_image*` + `live_capture?` + `live_frames[]?`; requires `Idempotency-Key`; parallel pipeline; returns verdict + evidence + provenance + latency |
| `/api/cases` | GET | List (role-scoped: officer=own, supervisor=unit, auditor=all; `verdict/status/limit/offset`) |
| `/api/cases/{id}` | GET | Full case (ownership-checked; `is_demo` from Gemini simulated) |
| `/api/cases/{id}/provenance` (+`/verify`) | GET | Signed provenance + HMAC verification |
| `/api/cases/{id}/override` | POST | `{action:clear\|deny\|escalate, reason≥3, version?}` + `If-Match`; RBAC: auditor never, officer never `deny`, escalated = supervisor-only; 409 on decided/version |
| `/api/audit` | GET | Auditor-only trail (`actor/entity/limit/offset`) |
| `/api/audit/verify` | GET | Supervisor/auditor hash-chain check |
| `/api/audit/access-review` | GET | Auditor registry-access aggregates (alerts >20) |
| `/api/fairness/report` | GET | Supervisor/auditor fairness + enrollment balance |
| `/api/citizens` | GET/POST | Search (misuse-gated, role-scoped) / create PENDING enrollment (supervisor, checksum + photo validated) |
| `/api/citizens/requests`(+`/list`), `/approve`, `/reject` | GET/POST | Dual-approval queue (four-eyes: approver ≠ requester) |
| `/api/citizens/import` | POST | HMAC-signed authority batch (`X-Import-Signature`, 1–500 records) |
| `/api/citizens/reconciliation/report`(+`/run`) | GET/POST | Read-only report / persist `last_reconciled_at` (supervisor) |
| `/api/citizens/{id}` | DELETE | Create PENDING delete request (supervisor) |
| `/api/citizens/orphans`(+`/check`, `/cleanup`) | GET/POST | Orphan biometric scan + secure-delete cleanup |
| `/api/evidence/token/{filename}`, `/view?token=`, `/{filename}` | GET | Signed evidence issuance (ownership-checked) + consumption (token or session) |
| `/api/health` | GET | `{healthy, version, database}` (public) |
| `/{full_path}` | GET | SPA fallback from `frontend/dist` (must stay last; `api/*` → 404 JSON) |

Auth on all except login/health/evidence-view-token/SPA. See `backend/app.py` for exact gates.

### 5. Non-functional notes for the demo
- **Latency:** tamper <1.5s and physical <5s are tested; sub-2.5s end-to-end is aspirational (sequential OCR + 3× InsightFace + Gemini). `total_latency_ms` is measured per screen.
- **Error handling:** Any module failure degrades to "inconclusive" for that module and routes the case to at least Yellow, never crashing the pipeline. Pipeline exceptions release the idempotency claim so same-key retry proceeds.
- **Idempotency:** `Idempotency-Key` 8–128 chars `[A-Za-z0-9\-_:.]` (UUID v4). Same key+session+input replays (`deduplicated:true`); same key+different input/session → 422; in-flight → 409; same input+different key within 10 min replays (`duplicate_of_key`).
- **Evidence:** No public mount (`/evidence/*` → 404). Authenticated signed URLs (`expires_in` 30–3600s, default 300) with traversal guards and `Cache-Control:no-store`.
- **Privacy & Compliance:** Aadhaar masking (`XXXX-XXXX-1234`) is required but currently unenforced end-to-end (see Tracker gap). Never log passwords, tokens, biometrics/embeddings, or full Aadhaar; audit `__repr__` is PII-free.

### 6. Open technical questions — resolved
- Deepfake model: FFT heuristic (no trained weights; revisit with labeled set).
- Specimens: synthetic set shipped (`samples/` + `L898902C3` seed); Aadhaar/PAN/Voter specimens still TODO for full multi-doc demo.

### 7. Production architecture (reference — see source PDF for full detail)
Microservices (OCR, Tamper, Deepfake, Face Match, Liveness, DB Lookup) behind an API Gateway, connected by Kafka, writing to a shared PostgreSQL/Redis case record; a Risk Engine service waits on all results (with timeout) and pushes verdicts to the officer dashboard over WebSocket; every stage and officer action is written to an immutable audit log. Deployed on Kubernetes on government-empanelled cloud or on-prem, with edge deployment for low-connectivity checkpoints.
