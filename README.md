# Python Rule-Based Fake Identity & Document Screening System

**Smart India Hackathon (SIH) — Problem Statement 26188**  
**Organization:** Ministry of Home Affairs (MHA) / Sashastra Seema Bal (SSB)  
**Domain:** Smart Automation / Homeland Security / Border Checkpoint Screening  

---

## 1. Overview

At border checkpoints, immigration and security officers manually inspect passports, visas, and traveler faces to detect forgeries, imposter substitution, and altered documents. This manual process is slow, subjective, and prone to missing sophisticated physical and digital fabrications.

This system provides an **AI-assisted forensic screening tool** that evaluates travel credentials and biometric identity in real time (under 3 seconds) across 6 forensic layers, presenting explainable visual evidence and a composite risk rating (Green / Yellow / Red) to the officer.

### Core Philosophy: Human-in-the-Loop
- **The system only flags risk; only a human officer can deny entry.**
- Every recommendation is accompanied by per-module explainable evidence rather than a black-box score.
- All assessments and human overrides are written to an append-only audit trail.

---

## 2. System Architecture

```
                                   [ SCREENING KIOSK ]
                             (React + TypeScript + Tailwind)
                                      │              │
                     1. Upload Document Image        2. Live Webcam Frame Burst
                                      │              │
                                      ▼              ▼
                               ┌─────────────────────────────┐
                               │       FastAPI Gateway       │
                               │   (Single-Process Engine)   │
                               └──────────────┬──────────────┘
                                              │
               ┌──────────────────────────────┴──────────────────────────────┐
               │                  FORENSIC SCREENING PIPELINE                │
               ▼                                                             ▼
┌──────────────────────────────┐                              ┌──────────────────────────────┐
│  1. Document Classifier      │                              │  5. 3-Way AI Face Match      │
│  Rule-Based & Layout Scan    │                              │  Google Gemini Multimodal AI │
│  • Aadhaar / PAN / Voter ID  │                              │  • Live vs. Doc Photo        │
│  • Indian Passport           │                              │  • Doc Photo vs. DB Record   │
└──────────────┬───────────────┘                              │  • Live vs. DB Record        │
               │                                              │  • Biometric Reasoning       │
┌──────────────▼───────────────┐                              └──────────────┬───────────────┘
│  2. OCR & Demographic Parse  │                                             │
│  Tesseract + Regex Parsers   │                              ┌──────────────▼───────────────┐
│  • UID / PAN / EPIC / PassNo │                              │  6. Dynamic Liveness Check   │
│  • Name, DOB, Address        │                              │  MediaPipe FaceLandmarker    │
└──────────────┬───────────────┘                              │  • Eye-Aspect-Ratio (EAR)    │
               │                                              │  • Blink Burst Analysis      │
┌──────────────▼───────────────┐                              └──────────────┬───────────────┘
│  3. Database Cross-Check     │                                             │
│  `citizens_registry` Table   │                              ┌──────────────▼───────────────┐
│  • Name & DOB Discrepancy    │                              │  7. Watchlist / Lookout DB   │
│  • Address Parity Check      │                              │  Mocked Government Registry  │
└──────────────┬───────────────┘                              │  • "MOCKED DATA" Labeled     │
               │                                              └──────────────┬───────────────┘
┌──────────────▼───────────────┐                                             │
│  4. Tamper & Deepfake Checks │                                             │
│  • ELA & Copy-Move Detector  │                                             │
│  • 2D Fourier (FFT) Anomaly  │                                             │
└──────────────┬───────────────┘                                             │
               └──────────────────────────────┬──────────────────────────────┘
                                              │
                                              ▼
                               ┌─────────────────────────────┐
                               │         RISK ENGINE         │
                               │   Rule-Based Composite Flag │
                               │   (Green / Yellow / Red)    │
                               └──────────────┬──────────────┘
                                              │
                                      ┌───────┴───────┐
                                      ▼               ▼
                        [ OFFICER DASHBOARD ]   [ IMMUTABLE AUDIT LOG ]
                        • Visual Evidence Cards • Append-Only Ledger
                        • Demographic Parity    • Officer Override History
                        • 3-Way Face Verdicts   • Complete Event Trail
```

---

## 3. Forensic Screening Modules

| # | Module | Technology / Engine | Detection Objective |
|---|---|---|---|
| **1** | **Document Classification** | Rule-Based CV & Layout Scanner | Detects whether uploaded document is an Aadhaar Card, PAN Card, Voter ID (EPIC), or Passport via emblem/watermark keywords, aspect ratio, and layout structure. |
| **2** | **OCR & Demographic Extraction** | Tesseract OCR + PassportEye + Regex | Extracts core identity attributes: Full Name, Date of Birth, Document Number, Address/Father's Name, and ICAO 9303 checksums. |
| **3** | **Database Cross-Verification** | Demographic Reconciliation Engine | Cross-references extracted details against the official `citizens_registry` database. Flags discrepancies in Name, DOB, Address, or ID number. |
| **4** | **Tamper Detection** | Error Level Analysis (ELA) + Block NCC | Detects localized image splicing, digital tampering, and copy-move duplicates. Generates a visual ELA heatmap overlay. |
| **5** | **Deepfake Detection** | 2D Fourier Transform (FFT) | Measures high-frequency radial energy ratios and spectral peakedness to identify generative AI / GAN upsampling artifacts. |
| **6** | **3-Way Face Verification** | Google Gemini (1.5/2.0 Flash) Multimodal AI | Conducts simultaneous 3-way comparative verification between: (a) Live Webcam Still, (b) Document Photo Crop, and (c) Database Registry Record. Returns pairwise match flags and detailed biometric reasoning. |
| **7** | **Liveness Detection** | MediaPipe FaceLandmarker | Analyzes a 12-frame rapid burst from the webcam. Tracks Eye Aspect Ratio (EAR) swings to detect natural blinking, preventing static photo and screen replay attacks. |
| **8** | **Watchlist Lookup** | `WatchlistProvider` Abstraction | Queries high-risk traveler registries (e.g., Lookout Circulars, Interpol Red Notices). Prominently labeled with a violet **"MOCKED DATA"** badge. |

---

## 4. Key Architectural Decisions

1. **Why Google Gemini for Face Verification:**
   - Evaluated against NVIDIA NIM and Groq. Gemini Flash provides native multi-image support (accepting 3 images in one prompt) and robust explainability without triggering biometric false-refusals.
   - Bypasses local C++ compilation and GPU requirements on Windows, executing in ~1.5s via cloud inference.
2. **Dual Database Engine:**
   - PostgreSQL schema defined with 7 tables (`officers`, `screening_cases`, `extracted_fields`, `module_results`, `officer_actions`, `audit_log`, `watchlist_entries`).
   - Runs out-of-the-box on SQLite for zero-setup local demonstrations and seamlessly connects to PostgreSQL in production environments.
3. **Fault Isolation Guarantee:**
   - If any single AI module encounters a network timeout or decoding error, it degrades to `status="inconclusive"` and elevates case risk to at least Yellow. The pipeline never crashes.

---

## 5. Repository Structure

```text
├── Appflow.md                 # Screen-by-screen application flow
├── Design.md                  # UI/UX design tokens and layout specifications
├── Implementationplan.md      # Sprint execution roadmap
├── PRD.md                     # Product Requirements Document (SIH 26188)
├── Rules.md                   # System non-negotiables and coding guardrails
├── Schema.md                  # Database relational schema
├── Techspec.md                # Technical specification & API contracts
├── Tracker.md                 # Live task & open-items tracker
├── audit.md                   # Comprehensive technical health & findings audit
├── pipeline/                  # ML/CV forensic pipeline modules
│   ├── common.py              # Shared result contracts and image loaders
│   ├── ocr_mrz.py             # Module 1: OCR & ICAO checksum parser
│   ├── tamper.py              # Module 2: ELA & copy-move detector
│   ├── deepfake.py            # Module 3: FFT spectral analyzer
│   ├── face_match.py          # Module 4: 3-Way AI face verification
│   └── liveness.py            # Module 5: MediaPipe blink EAR liveness
├── samples/                   # Specimen test documents and face datasets
│   ├── genuine_doc.png        # Synthetic genuine passport with valid MRZ
│   ├── tampered_doc.png       # Forged specimen with copy-move patch & splice
│   ├── faces/                 # Person A (match) and Person B (mismatch)
│   └── live/                  # 12-frame blink burst and static burst assets
└── tests/
    └── test_pipeline.py       # End-to-end integration tests
```

---

## 6. Getting Started

### Prerequisites
- Python 3.11+ (recommended via `uv`)
- Node.js 18+ and npm
- Tesseract OCR (Windows: `winget install UB-Mannheim.TesseractOCR`)
- Google Gemini API Key (free from Google AI Studio)
- Supabase PostgreSQL account (free tier from [supabase.com](https://supabase.com)) or local SQLite fallback

### Environment Setup
```powershell
# 1. Clone the repository
git clone https://github.com/soumyajit-cys/Python Rule-Based-Fake-Identity-Document-Screening-System.git
cd Python Rule-Based-Fake-Identity-Document-Screening-System

# 2. Create virtual environment
uv venv --python 3.11 .venv
.venv\Scripts\Activate.ps1

# 3. Install Python dependencies
uv pip install -r requirements.txt

# 4. Configure environment variables in .env:
# GEMINI_API_KEY="your_api_key_here"
# DATABASE_URL="postgresql+asyncpg://postgres:[password]@db.[ref].supabase.co:5432/postgres"
# (If DATABASE_URL is omitted, the system defaults to local offline SQLite: sqlite+aiosqlite:///screening.db)

# 5. Verify runtime assets (liveness model + tesseract OCR):
bash scripts/setup_vendor.sh
# The liveness model (face_landmarker.task) is committed to the repo; the
# script re-downloads it only if removed. Tesseract OCR must be installed on
# the machine (see the apt/winget commands printed by the script) for
# OCR/MRZ/demographic extraction to work. Without it, OCR and checksum
# degrade to "inconclusive / N-A" and the document cannot be verified.

# 6. Run test suite
python -m pytest tests/ -v
```

---

## 7. SIH Demo Scenarios (PRD §7)

1. **Clean Clearance:** Genuine Document (Aadhaar/Passport) + Matching Live Face + Matching DB Record ➔ **GREEN (Auto-Clear)**
2. **Demographic Forgery:** Physical Document with Forged/Altered Date of Birth vs. Official Database Record ➔ **RED / YELLOW** (Field-by-field demographic discrepancy table highlights altered birthdate)
3. **Physical Tampering:** Tampered/Altered Credential Image ➔ **RED / YELLOW** (Interactive ELA residual heatmap overlay highlights spliced zones)
4. **Identity Imposter:** Genuine Document + Mismatched Live Face ➔ **RED** (3-way face verification flags biometric discrepancy with explainable forensic analysis)
5. **Watchlist Hit:** Flagged Subject on Lookout Circular ➔ **RED (HIGH RISK)** (Prominent violet "MOCKED DATA" badge displayed)
