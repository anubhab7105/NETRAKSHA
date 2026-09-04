# Tracker
## MVP Build — Task & Open-Items Tracker

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done

---

### 0. Open questions — resolve before/during the day noted
Nothing here should be silently assumed away; update this table the moment an answer is confirmed, and reflect it back into the relevant doc (Techspec.md / Implementationplan.md / Design.md).

| Item | Source | Status | Needed by |
|---|---|---|---|
| Design visual direction (color palette, any brand reference) | Design.md §1 (proposed default in use) | **Open — default assumed** | Day 1 frontend scaffold |
| Password-hashing approach for `officers` table | Shema.md §4 | **Open — default assumed (bcrypt/passlib)** | Day 1 |
| Specimen document/test-face gap-fill (partially available — exact gaps not yet inventoried) | Implementationplan.md Day 1 | **Open** | Day 1 |

Resolved (for reference):
| Face verification architecture | **Resolved.** Multimodal Vision AI (**Google Gemini 1.5/2.0 Flash**) selected over NVIDIA NIM and Groq. Conducts 3-way cross-verification: Live Webcam vs. Document Photo vs. Database Registry Record. Solves Windows Python 3.13 wheel/C++ compilation blocker and produces detailed biometric explainability. `google-generativeai` already present in environment. |
| Deepfake detector model/weights | **Fallback used.** No pretrained classifier integrated → FFT/spectral frequency-artifact heuristic per Techspec §3, documented in `pipeline/deepfake.py`. No trained GAN/diffusion classifier. OK for MVP; revisit if a labeled set becomes available. |
| GPU availability | **Docs say "available"; this dev box has NO GPU / no nvidia-smi.** Shifting face verification to Gemini Multimodal API eliminates local GPU dependency while running OCR, Tamper, Deepfake, and Liveness seamlessly on CPU. |
| Tesseract | Docs mandate Tesseract; **system tesseract not installable (no sudo)** → vendored a working tesseract 5.5.0 + libs + eng.traineddata into `pipeline/vendor/tesseract/`; pytesseract + PassportEye pointed at it in-process. |
| Tamper detection method | Techspec §3 mandates "ELA + ORB copy-move". **ORB was trialed but hallucinated offset clusters on structurally-repeating synthetic pages**; copy-move now uses block normalized cross-correlation (dominant-offset cluster), a classical copy-move technique, kept alongside ELA. See Divergences below. |
| Sprint length | ~6 days |
| Storage | **Resolved.** Supabase PostgreSQL (primary cloud PostgreSQL with live app dashboard for evaluators and zero Windows setup) + SQLite async engine (local offline fallback). |
| Auth | Real login required (not mock) |

### 0b. Docs-vs-reality divergences (flagged per Rules.md)
- **Face Verification**: Previous docs assumed local InsightFace/ArcFace; updated to **Google Gemini Multimodal Vision API (3-way: Live vs Doc vs DB)** to provide explainable forensic reasoning and bypass Windows local C++ compilation hurdles.
- **GPU**: Implementationplan.md/Techspec §2 say GPU confirmed; the runtime has none. Gemini API handles face verification in the cloud; remaining modules run on CPU.
- **Tesseract**: not system-installable → vendored runtime under `pipeline/vendor/tesseract/` (gitignored). Startup note in `ocr_mrz._configure_tesseract()`.
- **Tamper**: ORB copy-move alone proved unreliable on the flat/structure-repeating synthetic specimens (false offset clusters); replaced ORB-only with **block NCC copy-move (dominant offset) + ELA**. Classical CV, spec-aligned in intent but method differs — flagged for review.
- **Liveness sample**: blink synthesis only reads as "closed" on a hi-res face (512px) — a 220px face's eye boxes were too small for EAR to drop, and an aggressive fill broke mediapipe face detection. Generator uses a 512px face + pad≈8.5% of height.
- **Specimens**: faces are public Olivetti academic photos (not real ID photos); documents are synthetic renders on a textured background so classical tamper gets a real signal.

---

### 1. Backend / infra
- [ ] FastAPI skeleton + 7 endpoints (`/login`, `/logout`, `/screen`, `/cases`, `/cases/{id}`, `/cases/{id}/override`, `/audit`)
- [ ] Database stood up locally (Postgres/SQLite dual engine), schema applied (`officers`, `citizens_registry`, `screening_cases`, etc.)
- [ ] `officers` table + real login/session handling (JWT/bcrypt)
- [ ] `citizens_registry` mock seed dataset (Aadhaar, PAN, Voter ID, Passport records)
- [ ] `WatchlistProvider` interface + mocked lookup table

### 2. Pipeline modules
- [ ] Document Classifier (rule-based visual/text scanning: Aadhaar, PAN, Voter ID, Passport)
- [x] OCR/MRZ parser (Tesseract + PassportEye + ICAO checksum for passports)
- [ ] Multi-document OCR parsers (Aadhaar UID/DOB/Address, PAN No/Name/DOB, Voter ID EPIC)
- [ ] Demographic DB Cross-Verification (Name fuzzy match, DOB strict check, Address parity vs `citizens_registry`)
- [x] Tamper detection (ELA + block NCC copy-move) — genuine ≈ 0.0001 vs tampered ≈ 0.79 on specimens (optimization needed for speed)
- [x] Deepfake detection (FFT frequency-artifact heuristic — **open item resolved**, see Open questions)
- [ ] Face verification (3-way Gemini Multimodal API: Live vs Doc vs DB with forensic reasoning)
- [x] Liveness (blink/EAR, mediapipe tasks API)
- [ ] Risk Engine (rule-based scoring, demographic mismatch rule, hard-flag rule)
- [x] Module-failure → "inconclusive" → force ≥ Yellow, **verified for each module individually** (bad path, blank image, empty burst) in `tests/test_pipeline.py`

### 3. Frontend
- [ ] Login screen (role-gated)
- [ ] Dashboard / case list (role-gated, status badges)
- [ ] New Screening — capture (doc upload with classification preview + webcam frame burst + DB citizen selector)
- [ ] Case Result — verdict banner + Document Badge + Demographic Reconciliation Table + 6 module evidence panels (including 3-Way Face Match) + "MOCKED DATA" badge on Watchlist
- [ ] Decision panel → `POST /cases/{id}/override`
- [ ] Case Detail (history, read-only)
- [ ] Audit Trail (read-only)

### 4. Data
- [x] Source/create genuine passport sample — `samples/genuine_doc.png` (valid ICAO MRZ)
- [x] Source/create tampered passport sample — `samples/tampered_doc.png` (copy-move duplicate + splice)
- [ ] Source/create Aadhaar sample (genuine + demographic mismatch specimen)
- [ ] Source/create PAN card sample
- [ ] Source/create Voter ID sample
- [x] Source/create mismatch-face pair — `samples/faces/person_a.png` vs `person_b.png` (mismatch), `person_a_2.png` (same-person match)
- [ ] Seed `citizens_registry` database records matching all specimen documents

### 5. Demo readiness (Prd.md §7 success criteria)
- [ ] Clean traveler: genuine document + matching DB record + matching live face → Green
- [ ] Demographic forgery: document with altered DOB/Name vs DB record → Red/Yellow with discrepancy highlighted
- [ ] Tampered document: copy-move / splice → Red/Yellow with ELA overlay
- [ ] Face mismatch: imposter / photo substitution → Red/Yellow with 3-way discrepancy shown
- [ ] Watchlist hit: flagged individual → Red with "MOCKED DATA" badge
- [ ] Every screening creates an immutable audit trail entry

### 6. Explicitly not tracked here (Prd.md §4 non-goals)
Kubernetes/microservices/Kafka, real DB/watchlist integration, bias/fairness certification, penetration testing, DPDP sign-off, multi-checkpoint/HA. Do not open tasks for these against this tracker — they belong to the post-hackathon roadmap (source PDF §11).