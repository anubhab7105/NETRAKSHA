#!/usr/bin/env bash



set -euo pipefail

pip install -r requirements.txt







if [ "${DISABLE_LOCAL_FACE_ENGINE:-}" = "true" ]; then
  echo "[build] DISABLE_LOCAL_FACE_ENGINE=true — skipping model provisioning (face engine disabled)"
else
  # Never fail the build on model download: the backend prewarms and degrades gracefully at startup.
  bash scripts/setup_vendor.sh || true
fi

if [ -f frontend/package-lock.json ]; then
  npm --prefix frontend ci
else
  npm --prefix frontend install
fi
npm --prefix frontend run build
