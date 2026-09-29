# System Architecture & Pipeline

## System Architecture


```
                         ┌─────────────────────────────────┐
                         │       SCREENING KIOSK (Browser)  │
                         │  React 19 + Vite 8 + Tailwind 4  │
                         │  JS/JSX only · oxlint · axios    │
                         └──────────────┬──────────────────┘
                                        │  multipart/form-data
                    ┌───────────────────┴───────────────────┐
                    │         FastAPI Gateway (single proc)  │
                    │  backend/app.py  ·  :8000  ·  /api/*  │
                    └───────────────────┬───────────────────┘
                                        │
              ┌─────────────────────────┴─────────────────────────┐
              │            FORENSIC SCREENING PIPELINE             │
              │  Sequential OCR pre-pass ─► Parallel local CV      │
              │  + Gemini cloud (asyncio.gather + run_in_executor) │
              └──────┬─────────────────┬────────────────┬──────────┘
                     │                 │                │
        ┌────────────▼──────┐ ┌────────▼────────┐ ┌─────▼─────────────┐
        │ OCR & Checksums   │ │ Tamper          │ │ Physical Forgery  │
        │ Tesseract (psm6)  │ │ ELA (q=90) +    │ │ layout / MRZ-font │
        │ PassportEye MRZ   │ │ SHA1 block-hash │ │ photo-frame / moiré│
        │ Verhoeff/ICAO/    │ │ copy-move       │ │ QR / guilloche    │
        │ PAN/EPIC + Gemini │ │ <1.5 s          │ │ <5 s              │
        └────────────┬──────┘ └────────┬────────┘ └─────┬─────────────┘
                     │                 │                │
        ┌────────────▼──────┐ ┌────────▼────────┐ ┌─────▼─────────────┐
        │ Deepfake (FFT)    │ │ Face Match (×3) │ │ Liveness + Iris   │
        │ radial spectrum   │ │ InsightFace     │ │ MediaPipe EAR +   │
        │ high_freq + peak  │ │ buffalo_l LOCAL │ │ motion + moiré    │
        │ + rolloff         │ │ 3-way hybrid    │ │ RGB iris (Hamming)│
        └────────────┬──────┘ └────────┬────────┘ └─────┬─────────────┘
                     │                 │                │
        ┌────────────▼──────┐ ┌────────▼────────┐ ┌─────▼─────────────┐
        │ Demographic       │ │ Watchlist       │ │ Gemini Scanner    │
        │ token-sort fuzzy  │ │ Provider (mock/ │ │ google-genai SDK  │
        │ DOB strict + trust│ │ DB) is_mocked   │ │ cascade + simulate│
        └────────────┬──────┘ └────────┬────────┘ └─────┬─────────────┘
                     └─────────────────┴────────────────┘
                                       │
                            ┌──────────▼──────────┐
                            │    RISK ENGINE      │
                            │ Green / Yellow / Red│
                            │ hard flags + score  │
                            └──────────┬──────────┘
                                       │
                        ┌──────────────┴──────────────┐
                        ▼                             ▼
              ┌───────────────────┐       ┌─────────────────────┐
              │ OFFICER DASHBOARD │       │ IMMUTABLE AUDIT LOG │
              │ Evidence cards    │       │ hash chain + HMAC   │
              │ 3-way verdicts    │       │ provenance bundles  │
              └───────────────────┘       └─────────────────────┘
```

**Request flow** (`backend/app.py:984`):

1. `POST /api/screen` authenticates via Bearer JWT, validates `Idempotency-Key`, hashes inputs, derives iris eye-crop from the same burst when available.
2. **OCR pre-pass** (Tesseract + PassportEye) extracts demographics for registry lookup.
3. **Parallel stage** — `asyncio.gather` runs local CV (`tamper`, `physical_forgery`, `deepfake`, `liveness`, local 3-way `face_match`, iris) concurrently with the **Gemini cloud call** (cascading model fallback, 10 s per-model timeout).
4. **Reconciliation** — demographic fuzzy match + registry trust tier + watchlist lookup + iris verification.
5. **Risk engine** produces verdict/flags/recommendations; the case, fields, module results, provenance, and audit entries are persisted.
6. Evidence PNGs are written to `SCREEN_EVIDENCE_DIR` or `samples/evidence/` and served only via **signed, expiring URLs** (`/api/evidence/token|view|{filename}`).

---

## Forensic Pipeline


### 6.1 Contract

Every `run_*` obeys the non-negotiable contract (`pipeline/common.py:104`):

```python
ModuleResult(
    module_name: str,          # e.g. "tamper", "face_match"
    score: float | None,       # 0–1 when ok, None when inconclusive (clipped via np.clip)
    status: "ok" | "inconclusive",
    raw_output: dict,          # full evidence for UI + audit (reason[:200] when inconclusive)
    evidence_uri: str | None,  # path to evidence PNG or None
)
```

Helpers: `ok_result(...)` and `inconclusive_result(module, reason)` (`pipeline/common.py:144`). **Any `inconclusive` forces verdict ≥ Yellow** (`pipeline/risk_engine.py:226`).

| Rule | Effect |
|---|---|
| Evidence-write failures | Swallowed, logged, never crash the case |
| `physical_forgery` sub-checks | Each isolated in `try/except` — one broken check never kills the module |
| `POST /api/screen` | Never 500s on module failure — faults degrade, the case always completes |

### 6.2 Modules

| # | Module | File | Engine | What it detects | Evidence |
|---|---|---|---|---|---|
| 1 | **OCR & MRZ** | `pipeline/ocr_mrz.py` | Tesseract `pytesseract --psm 6` + PassportEye MRZ + regex + Gemini classifier | Full Name, DOB, Doc Number, Address/Father's Name, ICAO 9303 checksums | Parsed MRZ + ICAO block checks |
| 2 | **Checksums** | `pipeline/checksums.py` | Pure Python: Verhoeff (Aadhaar-12), ICAO (7,3,1), `[A-Z]{5}[0-9]{4}[A-Z]` (PAN), `[A-Z]{3}[0-9]{7}` (EPIC) | Eliminates AI digit hallucination; dispatch via `validate_document_number` | `valid` + `method` |
| 3 | **Demographic** | `pipeline/demographic.py` | Token-sort Levenshtein (name ≥ 0.85, addr ≥ 0.60) + strict DOB/ID | Cross-references `citizens_registry`; critical fields: Full Name, DOB, Document Number | `comparisons[]`, `mismatch_fields`, `critical_mismatches` |
| 4 | **Tamper** | `pipeline/tamper.py` | **ELA** (JPEG q=90 residual, JET overlay) + **exact-duplicate SHA1 block-hash copy-move** (not ORB/NCC) | Splicing + copy-move duplicates; must be **< 1.5 s** (tested) | `tamper_<id>.png` ELA overlay |
| 5 | **Physical Forgery** | `pipeline/physical_forgery.py` | 6 deterministic sub-checks: `layout` (aspect + MRZ lines + portrait zone) · `font_consistency` (MRZ monospace lattice + stroke CV) · `photo_boundary` (quad + frame remnants) · `print_scan` (FFT moiré + acutance) · `qr_barcode` (OpenCV + pyzbar) · `security_features` (guilloche prominence) — weighted mean over available checks (<5 s) | Re-typeset MRZ, swapped photo, print-scan counterfeits that ELA misses | Zone overlay `physical_<id>.png` |
| 6 | **Deepfake** | `pipeline/deepfake.py` | `numpy.fft.fft2` radial spectrum (`high_freq + peakedness + rolloff`), **no pretrained CNN** | GAN upsampling artifacts | `method=fft_frequency_artifact_heuristic` |
| 7 | **Face Match (hybrid)** | `pipeline/face_match.py` | **Local authoritative:** InsightFace `buffalo_l` (ArcFace `w600k_r50`, cosine, threshold **0.55**, `CPUExecutionProvider`) for all pairs with both inputs; **Cloud:** Gemini 3-way reasoning (`pipeline/gemini_scanner.py`); simulated cloud scores **excluded from verdict** | `live ↔ doc` (primary), `doc ↔ DB`, `live ↔ DB` via `run_three_way_match` | Side-by-side PNG + completeness `complete/partial/unavailable` |
| 8 | **Liveness** | `pipeline/liveness.py` | MediaPipe `face_landmarker.task` (468-pt EAR, adaptive threshold) + inter-frame motion + FFT moiré + head-yaw/mouth-open; challenges `blink / head_turn / mouth_open` ; `MIN_BURST=3`, `LIVE_THRESHOLD=0.45` | 14-frame burst defeats photo/screen replay; challenge miss is `challenge_not_observed:*` not a fail when another genuine action occurred | `blink_count`, `motion_score`, `screen_artifact_score` |
| 9 | **Iris** | `pipeline/iris.py` → `backend/biometric/iris/` | Classical Hough circles → polar unwrap (64×512) → Gabor → 512-byte template; Hamming threshold **0.32** (low-conf band 0.28–0.36) | RGB eye verification + PAD (temporal + moiré) | `quality`, `liveness`, `hamming_distance` |
| 10 | **Watchlist** | `pipeline/watchlist.py` | `WatchlistProvider` / `MockWatchlistProvider` (5 fictional entries) or DB-backed via `load_db_watchlist_provider` | `is_hit`, `is_mocked=True` controls violet **MOCKED DATA** badge | `hits[]`, `is_mocked` |
| — | **Quality / Fairness / Zones** | `pipeline/document_quality.py` · `pipeline/face_quality.py` · `pipeline/fairness.py` · `pipeline/security_zones.py` | Laplacian blur ≥ 50, brightness; face gates (blur/light/size/pose); in-memory fairness ledger; legacy ROIs | Gates (`recapture_requested`) + `GET /api/fairness/report` | Not standalone verdicts |

**Thresholds** — single source `pipeline/thresholds.json:1` (v1.0):

```json
{
  "face_match": 0.55, "face_low_conf_low": 0.45, "face_low_conf_high": 0.65,
  "tamper_high": 0.7, "tamper_moderate": 0.4,
  "deepfake_high": 0.7, "liveness": 0.45,
  "document_quality_blur": 50.0,
  "iris_match": 0.32, "iris_low_conf_low": 0.28, "iris_low_conf_high": 0.36
}
```

Calibrated on `samples/genuine_doc.png` (tamper 0.08) vs `samples/tampered_doc.png` (0.72), face pairs 0.93–0.95. Iris band is an **uncalibrated prototype** — re-tune on held-out data before production.

---

## Risk Engine


`pipeline/risk_engine.py:43` — `assess_risk(...) -> RiskAssessment(verdict, risk_score, flags, recommendations, module_summary)`

**Composite score** = mean of per-module risk components (0–1), then mapped:

```
Green  < 0.35 <  Yellow  < 0.65 <  Red
```

Hard flags **escalate** the minimum verdict (never de-escalate) — `_escalate` is `max(level)` (`pipeline/risk_engine.py:403`):

| Signal | Flag | Floor |
|---|---|---|
| `critical_mismatches` (Name/DOB/ID) | `DEMOGRAPHIC_CRITICAL_MISMATCH:*` | **Red** |
| Minor mismatches | `DEMOGRAPHIC_MISMATCH:*` | Yellow |
| `citizens_registry` trust `unverified` | `UNVERIFIED_REGISTRY_SOURCE` | **Yellow** (Green forbidden) |
| `legacy` trust | `LEGACY_REGISTRY_NEEDS_REVERIFICATION` | informational |
| Local face `live ↔ doc` mismatch (`match==False`, outside low-conf band) | `FACE_MISMATCH` | **Red** |
| Low-conf face band 0.45–0.65 | `FACE_LOW_CONFIDENCE:0.xxx` | **Yellow** (bias mitigation — always manual review) |
| Evidence-backed registry mismatch (`db_face_pairs.evidence=="local"` + `doc_vs_db`/`live_vs_db == False`) | `DOC_DB_FACE_MISMATCH` / `LIVE_DB_FACE_MISMATCH` | **Red** (simulated guesses ignored) |
| Watchlist hit | `WATCHLIST_HIT` | **Red** |
| Tamper ≥ 0.7 / ≥ 0.4 | `HIGH_TAMPER_SCORE` / `MODERATE_TAMPER_SCORE` | **Red** / Yellow |
| Physical ≥ 0.7 / ≥ 0.4 | `HIGH_PHYSICAL_FORGERY_SCORE` / `MODERATE_…` | **Red** / Yellow |
| Deepfake ≥ 0.7 | `HIGH_DEEPFAKE_SCORE` | **Yellow** |
| Liveness `live==False` | `LIVENESS_FAILURE` | **Yellow** |
| Any module `inconclusive` | `*_INCONCLUSIVE` | **Yellow** |
| Iris mismatch / poor quality / liveness fail | `IRIS_MISMATCH` / `IRIS_QUALITY_POOR` / `IRIS_LIVENESS_FAILED` | **Red** / Yellow / Yellow |

Bias note: the face low-confidence band routes near-threshold scores to manual review to avoid unfair targeting of groups where the model is less certain.

---

## Frontend


`frontend/` — **React 19 + Vite 8 + Tailwind 4**, **JS/JSX only (no TypeScript)**, `oxlint` for linting.

| View | Route | Purpose |
|---|---|---|
| **Login** | `/login` | Username/password → JWT or `mfa_token` step-up; handles `PASSWORD_CHANGE_REQUIRED`/`MFA_SETUP_REQUIRED` 403s |
| **SecuritySetup** | `/change-password` | Forced password rotation + TOTP enrollment (QR + manual key + server time) |
| **Dashboard** | `/` | Case queue with verdict/status/unit filters, pagination, role-aware actions |
| **Scanner** | `/scan` | `WebcamCapture` (document `environment` + person burst) — 14-frame burst for liveness, downscaled JPEG for doc; `PersonBiometricCapture` feeds face+liveness+iris from **one** capture; `Idempotency-Key` minted per intent, regenerated on input change |
| **CaseReport** | `/case/:id` | Evidence cards (ELA, physical overlay, face side-by-side), demographic parity table, 3-way face completeness, liveness + iris signals, risk flags + recommendations, override form (optimistic locking) |
| **AuditTrail** | `/audit` | Hash-chained ledger with actor/action/entity filters + chain verification |
| **NotFound** | `*` | 404 |

**Key client details** (`frontend/src/api.js:1`, `frontend/vite.config.js:1`):

- `resolveBaseURL()` — `DEV` or `:8000` → same-origin `/api`; `netraksha.xyz`/`www`/`sih-weld-psi.vercel.app`/`*.up.railway.app` → `/api` (avoids CORS); otherwise `VITE_API_BASE_URL` (must end `/api`) or fallback `/api`.
- Interceptors — attach `Authorization`, wipe `localStorage` + redirect to `/login` on 401 (except step-up URLs), redirect to `/change-password` on 403 rotation/MFA gates.
- `apiErrorMessage` — unwraps FastAPI 422 array `detail` into human-readable `HTTP <status>: <msg>`.
- `GovTopBar` / `Sidebar` / `SEO` / `Breadcrumbs` / `ui` (`GovNotice`, `WorkflowSteps`, `PageHeader`).
- `vite.config.js` — `seoFiles()` emits `robots.txt`/`sitemap.xml`/`llms.txt` and replaces `%SITE_URL%` in `index.html`; `sourcemap:false` intentional; `manualChunks` for `react-vendor`/`router`/`lucide-icons`/`http-client`.

---

## Iris Biometrics (RGB Prototype)


> **Disclosure:** The current iris path is a **smartphone RGB prototype, not a dedicated NIR system**. See `docs/iris_architecture.md:1` and the `IrisCapture` UI notice. Expected EER is 5–15 % (vs 1–2 % for 850 nm NIR) and degrades with ambient light, distance, reflections, pupil dilation, and dark irises.

| Stage | Implementation |
|---|---|
| **Provider interface** | `BiometricProvider` (`backend/biometric/iris/provider.py`) — `RGBProvider` (current) + `NIRProvider` (stub, `ctypes`/`pyusb` path) via `get_provider("rgb"|"nir")` |
| **Segmentation** | Classical Hough circles on eye crop (`segmenter.py`) |
| **Normalization** | Polar unwrapping `64×512` (`normalizer.py`) |
| **Encoding** | Single Gabor filter → binary template `64×8` → 512 bytes (`encoder.py`) |
| **Matching** | Hamming distance, threshold `0.32` (low-conf band `0.28–0.36`) (`matcher.py`, `pipeline/thresholds.json:12`) |
| **Quality** | Blur, illumination, iris area (`quality.py`) |
| **PAD** | Temporal movement + FFT moiré + screen replay (`liveness.py`) |
| **Storage** | `iris_templates.template` encrypted at rest (HMAC+base64; production should use `Fernet`/`AES-GCM` with `IRIS_ENCRYPTION_KEY`); raw eye images deleted after enrollment (`unlink`) |

No learned weights yet. Future training data: `UBIRIS.v2`, `CASIA-Iris-Thousand` (check licenses), with heavy augmentation for phone capture.

---

## Known Gaps & Limitations


Preserved honestly — do not claim these as done until implemented:

- **Violet `MOCKED DATA` badge** and **Aadhaar `XXXX-XXXX-1234` masking** are spec'd but **unimplemented** (the badge currently renders as `HIT`/`CLEAR` chips + `is_mocked` notice).
- `VITE_SITE_URL` has a triple-default (`vite.config.js` / `vercel.json` / docs) — not yet single-sourced.
- `og-image` extension mismatch and `public/%SITE_URL%` placeholder are open bugs.
- `EvidenceImage` component hardcodes `/api` instead of `api.defaults.baseURL`.
- `handleVerify` is duplicated in two views.
- **CPU-only** — no GPU; InsightFace `CPUExecutionProvider` is correct but slower than the aspirational sub-2.5 s target.
- **Iris** is RGB-only (see §12) — do not present as NIR-grade.
- Evidence on ephemeral disks is wiped on restart unless `SCREEN_EVIDENCE_DIR` points at a persistent volume.

---
