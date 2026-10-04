#!/usr/bin/env bash
#
# Provision runtime assets for the screening pipeline.
#
#   * pipeline/vendor/models/face_landmarker.task — mediapipe FaceLandmarker
#     model required by the Liveness Detection module. The file is committed
#     to the repository; this script only re-downloads it if it was removed
#     (e.g. stripped by a .gitignore clean-up).
#   * tesseract — required by OCR & MRZ parsing (Module 2). A system install
#     is detected and reported; it is NOT bundled because it is platform
#     specific.
#
# Safe to run repeatedly.
#
# Windows: this is a bash script — run it under WSL (`wsl bash
#   scripts/setup_vendor.sh`) or Git Bash. There is no .ps1 equivalent on
#   purpose (model download + sha256sum are POSIX); native PowerShell users
#   should use WSL. Requires `python3` with the repo importable — the script
#   exports PYTHONPATH=$PROJECT_ROOT so `python3 -c "import pipeline…"`
#   works no matter where it is invoked from.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
MODEL_DIR="$PROJECT_ROOT/pipeline/vendor/models"
TASK="$MODEL_DIR/face_landmarker.task"
TASK_URL="https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
# Pinned SHA-256 of the upstream face_landmarker float16 v1 bundle (verify at
# https://developers.google.com/mediapipe/solutions/vision/face_landmarker).
TASK_SHA256="af23fc7c1ff21d034deaa2b7fc1d56bb670ce69a4cbdc9579b6f1afd680835f4"

echo "==> Screening runtime asset check"

# --- 1. mediapipe FaceLandmarker model -----------------------------------
if [[ -f "$TASK" ]]; then
  SIZE=$(wc -c < "$TASK" | tr -d ' ')
  echo "[ok] face_landmarker.task present ($SIZE bytes)"
else
  echo "[..] face_landmarker.task missing — downloading…"
  mkdir -p "$MODEL_DIR"
  curl -fSL --retry 3 -o "$TASK" "$TASK_URL"
  SIZE=$(wc -c < "$TASK" | tr -d ' ')
  if [[ "$SIZE" -lt 1000000 ]]; then
    echo "[!!] downloaded model looks truncated ($SIZE bytes) — remove $TASK and re-run" >&2
    exit 1
  fi
  echo "[ok] face_landmarker.task downloaded ($SIZE bytes)"
fi
if command -v sha256sum >/dev/null 2>&1; then
  ACTUAL_SHA=$(sha256sum "$TASK" | awk '{print $1}')
  if [[ "$ACTUAL_SHA" != "$TASK_SHA256" ]]; then
    echo "[!!] face_landmarker.task SHA-256 mismatch (got $ACTUAL_SHA, want $TASK_SHA256) — remove $TASK and re-run" >&2
    exit 1
  fi
  echo "[ok] face_landmarker.task SHA-256 verified"
fi

# --- 2. tesseract OCR -----------------------------------------------------
TESS="$(command -v tesseract || true)"
if [[ -n "$TESS" ]]; then
  echo "[ok] tesseract found: $TESS"
  for candidate in /usr/share/tesseract-ocr/5/tessdata /usr/share/tesseract-ocr/4.00/tessdata /usr/share/tessdata /opt/homebrew/share/tessdata; do
    if [[ -f "$candidate/eng.traineddata" ]]; then
      echo "[ok] tessdata: $candidate"
      break
    fi
  done
else
  echo "[..] tesseract NOT found. Installing it makes OCR/MRZ extraction work."
  echo "     Debian/Ubuntu: sudo apt-get install -y tesseract-ocr tesseract-ocr-eng"
  echo "     Fedora:        sudo dnf install -y tesseract"
  echo "     Windows:       winget install UB-Mannheim.TesseractOCR"
fi

# --- 3. InsightFace buffalo_l (local 3-way face legs) -----------------------
# The pack (~300MB) is gitignored on purpose — provision it here at
# build/deploy time so the first screening never pays a cold download (or
# fails every registry leg when the model zoo is unreachable). Reuses the
# same on-disk layout the pipeline expects (<root>/models/buffalo_l/).
# No SHA pin here: the pack is N files fetched by InsightFace itself and
# versioned upstream — integrity is checked by the ONNX loader at startup
# (corrupt files fail loudly in the [startup] prewarm log, never silently).
BUFFALO_DIR="$MODEL_DIR/models/buffalo_l"
if [[ -f "$BUFFALO_DIR/w600k_r50.onnx" && -f "$BUFFALO_DIR/det_10g.onnx" ]]; then
  echo "[ok] buffalo_l pack present ($BUFFALO_DIR)"
else
  echo "[..] buffalo_l pack missing — downloading via InsightFace (~300MB, one time)…"
  mkdir -p "$BUFFALO_DIR"
  if python3 -c "import insightface, onnxruntime" 2>/dev/null; then
    if python3 -c "
from pipeline.face_match import prewarm_local_engine
import sys
sys.exit(0 if prewarm_local_engine() else 1)
"; then
      echo "[ok] buffalo_l provisioned"
    else
      echo "[!!] buffalo_l download failed — the backend will prewarm (and loudly log) at startup instead" >&2
    fi
  else
    echo "[!!] insightface/onnxruntime not installed — install requirements first, then re-run" >&2
  fi
fi

echo "==> Done. Pipeline will run with full OCR + liveness only when both are present."