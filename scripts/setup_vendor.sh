#!/usr/bin/env bash













set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_DIR="$PROJECT_ROOT/pipeline/vendor/models"
TASK="$MODEL_DIR/face_landmarker.task"
TASK_URL="https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"

echo "==> Screening runtime asset check"


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