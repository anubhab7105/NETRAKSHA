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

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_DIR="$PROJECT_ROOT/pipeline/vendor/models"
TASK="$MODEL_DIR/face_landmarker.task"
TASK_URL="https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"

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

echo "==> Done. Pipeline will run with full OCR + liveness only when both are present."