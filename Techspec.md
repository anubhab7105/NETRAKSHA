# Technical Specification
## MVP Architecture

### 1. Architecture overview
Single-process FastAPI backend (matches the original hackathon prototype's shape, per the source doc), with each pipeline module implemented as an isolated Python module/function so it can later be lifted into its own microservice without a rewrite — this mirrors the "prototype vs production" migration path in the source architecture doc.

Request flow (MVP, synchronous):
```
Frontend (React)
   → POST /screen  (uploaded document image + live face burst + optional DB record ID)
      → 1. Document Classifier: Rule-based visual/text scanning (Aadhaar, PAN, Voter ID, Passport)
      → 2. OCR & Field Extractor: Tailored field parsing (UID/PAN/EPIC/Passport No, Name, DOB, Address)
      → 3. Database Demographic Cross-Check: Queries registered citizen record, reconciles fields (Name, DOB, Address)
      → 4. Tamper Detection: Error Level Analysis + Block NCC copy-move
      → 5. Deepfake Detection: FFT radial power spectrum analysis
      → 6. 3-Way AI Face Verification: Gemini Multimodal AI (Live vs Doc vs DB) + forensic reasoning
      → 7. Liveness Detection: MediaPipe EAR blink analysis on webcam burst
      → 8. Watchlist Lookup: High-risk lookout circular query
      → 9. Risk Engine: Composite weighted score + hard-flag rules (Green / Yellow / Red)
   → response: verdict + per-module evidence + demographic mismatch flags + 3-way facial reasoning
   → written to database (screening_cases + extracted_fields + module_results + audit_log)
```

No message queue, no separate services — every module runs as an isolated function call within one request for the demo. This keeps latency simple to reason about and removes an entire class of demo-day infrastructure risk.

### 2. Tech stack — MVP vs. production
| Layer | MVP (this build) | Production (source doc, future) |
|---|---|---|
| Backend | Python, FastAPI, single process | Python microservices behind Kong/API Gateway, gRPC internally |
| Frontend | React + TypeScript + Vite + Tailwind | Same, + React Query, WebSocket, shadcn/ui |
| Storage | Supabase PostgreSQL (cloud managed with live evaluator app dashboard) / SQLite async engine (local offline fallback) | PostgreSQL, encrypted object storage, Redis, immutable audit log store |
| Messaging | None (direct function calls) | Apache Kafka / RabbitMQ |
| Document Classification | Rule-based CV & Regex layout heuristics (Aadhaar, PAN, Voter ID, Passport) | Fine-tuned Document Layout Analysis CNN / LayoutLMv3 |
| OCR & Extraction | Single-Call Gemini 1.5/2.0 Flash Multimodal OCR + Algorithmic Checksums (Verhoeff for Aadhaar, ICAO 9303 for Passport, Regex for PAN/Voter) | Fine-tuned PaddleOCR / TrOCR + ICAO 9303 parser |
| Demographic Verification | In-memory & DB field reconciliation (fuzzy string match + strict DOB/ID check) | Real-time secure API integration with UIDAI, NSDL, ECI, and Passport Seva |
| Face verification | Multimodal Vision AI: Google Gemini 1.5/2.0 Flash (3-way comparison: Live vs Doc vs Database) | Dedicated sovereign vision microservice / Triton / ONNX + secure registry feeds |
| Tamper detection | ELA + Block NCC / ORB (classical CV, optimized <0.8s) | Trained CNN ensemble + classical checks |
| Deepfake detection | FFT frequency-artifact heuristic (spectral peakedness) | Dedicated trained GAN/diffusion-artifact classifier |
| Liveness | Blink/EAR heuristic, frame burst (MediaPipe) | Depth/texture anti-spoof CNN or certified SDK |
| Watchlist/DB | Mocked local lookup table (`WatchlistProvider`) | Secure mTLS integration with national registries |
| Deployment | `uvicorn` locally, frontend built static and served by FastAPI | Docker + Kubernetes, govt cloud/on-prem, Terraform, CI/CD |

### 3. Module specs (MVP)
For each: input → processing → output.

**Document Classification** — Input: document image. Identifies whether the document is an Aadhaar Card, PAN Card, Voter ID (EPIC), or Passport using visual keywords ("GOVERNMENT OF INDIA", "INCOME TAX DEPARTMENT", "ELECTION COMMISSION", "PASSPORT"), layout ratios, and pattern regexes. Output: `{document_type: str, confidence: float}`.

**OCR, Demographic Extraction & Checksums** — Input: document image + classified document type. Extracted via unified Gemini Multimodal scanner and verified with algorithmic checksums:
- *Aadhaar:* 12th-digit Verhoeff mathematical checksum algorithm.
- *Passport:* ICAO 9303 modulus-10 check-digit validation across document number, DOB, and expiry.
- *PAN:* Regex syntax validation (`[A-Z]{5}[0-9]{4}[A-Z]`).
Output: `{fields: dict, checksum_valid: bool, raw_text: str}`.

**Database Demographic Cross-Verification** — Input: extracted fields + citizen database records. Locates the registered citizen record via Document Number or Traveler ID. Performs field-by-field cross-checking:
- *Name:* Fuzzy string distance (Levenshtein / token sort ratio >= 0.85).
- *DOB:* Strict date parity check (flags forged birthdates).
- *Address:* Text similarity & pin code parity.
- *Document ID:* Exact alphanumeric match.
Output: `{matched: bool, discrepancy_count: int, field_comparisons: list[dict], db_record: dict}`.

**Tamper detection** — Input: document image. Optimized Error Level Analysis (JPEG recompression artifact map) + Block normalized cross-correlation for copy-move regions (< 0.8s runtime on CPU). Output: `{tamper_score 0-1, evidence_image_uri}`.

**Deepfake detection** — Input: face image/frame. FFT radial power spectrum analysis measuring high-frequency energy ratio and spectral peakedness. Output: `{deepfake_score 0-1}`.

**Face verification (3-way)** — Input: document photo crop + live capture still + database reference photo. Processed by Gemini 1.5/2.0 Flash via multi-image prompt. Evaluates 3 biometric pairings: (1) Live vs Doc, (2) Doc vs DB, and (3) Live vs DB. Output: `{similarity: float, match: bool, live_vs_doc_match: bool, doc_vs_db_match: bool, live_vs_db_match: bool, visual_reasoning: str, feature_analysis: dict}`.

**Liveness** — Input: short frame burst from webcam. Eye-aspect-ratio blink detection across frames (MediaPipe landmarks). Output: `{liveness_score 0-1, live: bool}`.

**Watchlist lookup** — Input: extracted name/ID number. Looks up a local JSON/CSV of mock "flagged" entries behind a `WatchlistProvider` interface (same shape a real registry client would implement later). Output: `{hit: bool, matched_entry?}`.

**Risk engine** — Input: all module outputs. Weighted rule-based scoring → Green / Yellow / Red. Hard flags:
- *Demographic mismatch (altered DOB/Name on document vs DB):* forces **RED** or **YELLOW**.
- *Watchlist hit:* forces **RED**.
- *Face verification failure:* forces **RED**.
- *Liveness failure:* forces at least **YELLOW**.
- *Module failure / inconclusive:* forces at least **YELLOW**.

### 4. API design (MVP)
| Endpoint | Method | Purpose |
|---|---|---|
| `/login` | POST | Authenticate officer (username/password), establish session — real login is confirmed scope (Schema.md `officers` table) |
| `/logout` | POST | End the officer's session (session termination per AppFlow.md §3.1) |
| `/screen` | POST | Submit document image + face capture + optional citizen ID, run full pipeline in parallel, return verdict |
| `/cases` | GET | List recent cases (for dashboard) |
| `/cases/{id}` | GET | Full case detail + per-module evidence |
| `/cases/{id}/override` | POST | Officer records a decision/override + reason (writes to audit log) |
| `/audit` | GET | Read-only audit trail |

### 5. Non-functional notes for the demo
- **Target Latency:** Sub-2.5 seconds end-to-end processing time for checkpoint/airport throughput. Achieved by running local CV (optimized ELA <0.8s, MediaPipe liveness) in parallel (`asyncio`) with the single-call Gemini Flash multimodal AI request (~1.4s).
- **Error handling:** Any module failure degrades to "inconclusive" for that module and routes the case to at least Yellow, never crashing the pipeline.
- **Privacy & Compliance:** Aadhaar numbers masked on UI (`XXXX-XXXX-1234`) per DPDP Act standards.

### 6. Open technical questions (flag to confirm)
- Any preferred pretrained deepfake-detection model/weights, or should the team pick one during build?
- Preferred sample/specimen document set, or does the team need to source/create synthetic ones?

### 7. Production architecture (reference — see source PDF for full detail)
Microservices (OCR, Tamper, Deepfake, Face Match, Liveness, DB Lookup) behind an API Gateway, connected by Kafka, writing to a shared PostgreSQL/Redis case record; a Risk Engine service waits on all results (with timeout) and pushes verdicts to the officer dashboard over WebSocket; every stage and officer action is written to an immutable audit log. Deployed on Kubernetes on government-empanelled cloud or on-prem, with edge deployment for low-connectivity checkpoints.