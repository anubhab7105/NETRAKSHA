# Tracker
## MVP Build — Task & Open-Items Tracker

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done

---

### 0. Open questions — resolve before/during the day noted
Nothing here should be silently assumed away; update this table the moment an answer is confirmed, and reflect it back into the relevant doc (Techspec.md / Implementationplan.md / Design.md).

| Item | Source | Status | Needed by |
|---|---|---|---|
| Design visual direction (color palette, any brand reference) | Design.md §1 (proposed default in use) | **Open — default assumed** | Day 1 frontend scaffold |
| Aadhaar/PAN/Voter specimen gap-fill (passport + faces + live bursts shipped; Indian-card specimens missing) | Implementationplan.md Day 1 | **Open** | Full multi-doc demo |
| Violet `MOCKED DATA` badge + Aadhaar `XXXX-XXXX-1234` masking (spec'd, not rendered) | Rules.md §1, Design.md §1/§5 | **Open — UI gap** | Before evaluator demo |
| Frontend SEO/site fixes (`SITE_URL` triple-default, `og-image.jpeg→.png`, `public/%SITE_URL%` verbatim, `EvidenceImage` hardcoded `/api`, duplicated `handleVerify`) | Design.md §6, `vite.config.js`, `CaseReport.jsx`, `AuditTrail.jsx` | **Open — bugs filed** | Before release |
| `pipeline/__init__.py` exports + `tamper.py` ORB docstring (code is exact-hash SHA1; init omits 5 modules) | `pipeline/__init__.py`, `tamper.py:174` | **Open — comment-only** | Anytime |

Resolved (for reference):
| Face verification architecture | **Resolved — hybrid.** Local InsightFace `buffalo_l` (authoritative matches, CPU fallback) + Gemini (`google-genai`, `gemini-3.6-flash`) reasoning + offline simulation (excluded from Red). Earlier "Gemini-only to dodge C++/GPU" notes are superseded. |
| Deepfake detector model/weights | **Fallback used.** No pretrained classifier → FFT/spectral heuristic (`method=fft_frequency_artifact_heuristic`). OK for MVP; revisit with labeled set. |
| GPU availability | **Resolved — CPU-only.** No GPU/`nvidia-smi` on dev box; `onnxruntime` falls back to `CPUExecutionProvider` (see provenance). Sub-2.5s is aspirational. |
| Tesseract | **Resolved — system install.** No vendored `pipeline/vendor/tesseract/` is shipped; `pipeline/common.py` resolves `shutil.which(tesseract)` + system `tessdata`. Install via `winget`/`apt`; `scripts/setup_vendor.sh` only checks. |
| Tamper detection method | **Resolved — ELA + exact-duplicate SHA1 block-hash.** ORB trialed (hallucinated on repeating synthetics); block NCC noted in older docs; shipped code hashes `8px` textured blocks (`COPY_FLOOR=10/COPY_SAT=90` locals). |
| Password hashing | **Resolved — passlib bcrypt only** (`bcrypt==4.0.1`); SHA fallback removed; dummy-verify unknown users. |
| Sprint length | ~6 days (build substantially complete) |
| Storage | **Resolved.** Supabase PostgreSQL primary + SQLite fallback; 10 tables; startup `ensure_*` self-heal; no Alembic. |
| Auth | **Resolved.** Real bcrypt + JWT (`purpose=session`, 8h) + supervisor TOTP + forced rotation + 5/300s throttles + unit scoping. Demo `officer1/Officer@123`, `supervisor1/Supervisor@123`, `auditor1/Auditor@123` (non-prod). |

### 0b. Docs-vs-reality divergences (closed except UI gaps above)
- **Face Verification**: hybrid local-authoritative (InsightFace decides; Gemini reasons; simulated excluded) — Gemini-only notes superseded.
- **Tesseract**: system dependency, not vendored.
- **Tamper**: exact-hash copy-move + ELA (see calibration in `thresholds.json`).
- **Frontend**: JS/JSX (no TypeScript), webcam-only capture (no upload/PDF), 14-frame burst, role gates officer+supervisor=Scanner / supervisor+auditor=Audit, auditor-only `/audit`, no confidence % / 3-image strip / EAR graph.
- **Liveness**: EAR + motion + moiré + yaw/mouth with randomized challenges (not blink-only).
- **Classifier**: no standalone module — Gemini profiles + physical aspects + zone templates.
- **Specimens**: Olivetti faces (academic, not ID photos); synthetic textured docs; seed `L898902C3` matches specimens.

---

### 1. Backend / infra
- [x] FastAPI single-process + canonical `/api/*` endpoints (auth/MFA/rotation, idempotent screen, cases/provenance/override, audit/verify/access-review, fairness, citizens governance, signed evidence, health, SPA fallback)
- [x] Dual engine + 10-table schema + startup self-heal (`ensure_*` + sequence re-anchor)
- [x] `officers` + real auth (JWT/TOTP/rotation/throttles/unit RBAC) + prod secret gates + bootstrap admin
- [x] `citizens_registry` mock seeds (Aadhaar/PAN/Voter/Passport + specimen match) + trust columns
- [x] `WatchlistProvider` + mocked table (`is_mocked=True`); controlled enrollment (four-eyes + HMAC import) + reconciliation + orphan cleanup
- [x] Hash-chained audit + signed provenance + authenticated evidence (no public mount)

### 2. Pipeline modules
- [x] OCR/MRZ parser (Tesseract + PassportEye + ICAO) + Gemini classifier/OCR (`google-genai`, simulated fallback)
- [x] Checksums (Verhoeff/ICAO/PAN/EPIC) + demographic reconciliation (fuzzy ≥0.85, strict DOB) + trust levels
- [x] Tamper (ELA + exact-hash copy-move) — genuine vs tampered separated; <1.5s asserted
- [x] Physical forgery (6 weighted checks + overlay) — <5s asserted
- [x] Deepfake (FFT heuristic)
- [x] Face verification (hybrid local-authoritative 3-way + Gemini reasoning; sim excluded from Red)
- [x] Quality gates (`document_quality`, `face_quality`), legacy `security_zones`, `fairness` ledger
- [x] Liveness (EAR/motion/moiré + challenges, MediaPipe task)
- [x] Risk Engine (mean + floors; demographic/face/watchlist → Red; trust/demo/recapture/inconclusive/liveness → ≥Yellow)
- [x] Module-failure → "inconclusive" → ≥ Yellow, verified per module (bad path, blank image, empty burst) in tests

### 3. Frontend
- [x] Login (password + TOTP step-up, throttles, drift hints) + SecuritySetup (rotation + MFA enroll)
- [x] Dashboard / case list (role-scoped; search by id/doctype)
- [x] New Screening — webcam doc + 14-frame burst + UUID idempotency (header + fallback)
- [x] Case Result — verdict + demographic table + tamper/physical/deepfake/face/liveness/checksum/zones/watchlist panels + provenance + RBAC override (versioned)
- [x] Case Detail (history, read-only) + Audit Trail (auditor-only + verify)
- [ ] Violet `MOCKED DATA` badge (watchlist + simulated Gemini) — chips/notices only today
- [ ] Aadhaar `XXXX-XXXX-1234` masking (raw values render today)
- [ ] SEO/site + `EvidenceImage` baseURL + `handleVerify` dupe fixes (see §0)

### 4. Data
- [x] Genuine passport `samples/genuine_doc.png` (valid ICAO MRZ)
- [x] Tampered passport `samples/tampered_doc.png` (copy-move + splice)
- [ ] Aadhaar sample (genuine + demographic mismatch specimen)
- [ ] PAN card sample
- [ ] Voter ID sample
- [x] Mismatch-face pair — `samples/faces/person_a.png` vs `person_b.png`, `person_a_2.png` (match)
- [x] Live bursts — `samples/live/blink_burst_*.png` (12) + `static_burst_*.png` (8)
- [x] Registry seeds matching specimens (`L898902C3 / Jasmine Specimen`); `face_landmarker.task` committed
- [x] Enrollment uploads dir + orphan hygiene (`samples/faces/uploads`)

### 5. Demo readiness (PRD.md §7 success criteria)
- [x] Clean traveler → Green (all local clear, no hard flags)
- [x] Demographic forgery → Red/Yellow with discrepancy highlighted
- [x] Tampered document → Red/Yellow with ELA + physical overlays
- [x] Face mismatch (local) → Red with pair breakdown
- [x] Watchlist hit → Red with mocked-source indication (badge TODO)
- [x] Every screening creates a hash-chained audit entry + provenance signature

### 6. Explicitly not tracked here (PRD.md §4 non-goals)
Kubernetes/microservices/Kafka, real DB/watchlist integration, bias/fairness certification, penetration testing, DPDP sign-off, multi-checkpoint/HA. Do not open tasks for these against this tracker — they belong to the post-hackathon roadmap (source PDF §11).
