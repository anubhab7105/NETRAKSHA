#!/usr/bin/env bash
# Native (no-Docker) build: Python deps + frontend production bundle.
# FastAPI serves frontend/dist same-origin, so no VITE_API_BASE_URL override
# is needed; VITE_SITE_URL bakes canonical/SEO URLs (defaults to netraksha.xyz).
set -euo pipefail

pip install -r requirements.txt

if [ -f frontend/package-lock.json ]; then
  npm --prefix frontend ci
else
  npm --prefix frontend install
fi
npm --prefix frontend run build
