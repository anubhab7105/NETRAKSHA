#!/usr/bin/env bash
# Native (no-Docker) build: Python deps + frontend production bundle.
# FastAPI serves frontend/dist same-origin, so no VITE_API_BASE_URL override
# is needed; VITE_SITE_URL bakes canonical/SEO URLs (defaults to netraksha.xyz).
set -euo pipefail

pip install -r requirements.txt

# Provision runtime models (face_landmarker.task check + buffalo_l ~300MB
# download attempt). Never fail the build: Render has no system Tesseract and
# the model zoo can be unreachable — the backend prewarms loudly at startup
# and degrades gracefully instead. `|| true` keeps `set -e` from aborting.
# When DISABLE_LOCAL_FACE_ENGINE=true (e.g. Render free tier), skip entirely
# to save build time and avoid downloading models that will never be loaded.
if [ "${DISABLE_LOCAL_FACE_ENGINE:-}" = "true" ]; then
  echo "[build] DISABLE_LOCAL_FACE_ENGINE=true — skipping model provisioning (face engine disabled)"
else
  bash scripts/setup_vendor.sh || true
fi

if [ -f frontend/package-lock.json ]; then
  npm --prefix frontend ci
else
  npm --prefix frontend install
fi
npm --prefix frontend run build
