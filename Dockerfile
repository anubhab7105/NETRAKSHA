# Netraksha — Cloud Run production image (single service).
#
# FastAPI (backend/app.py) serves the built React SPA from frontend/dist
# same-origin, so one container is enough. Mirrors the Render native build
# (build.sh): Python deps + vendor models + `npm run build`.
#
# Build:
#   docker build -t netraksha --build-arg VITE_SITE_URL=https://<your-url> .
# Run locally:
#   docker run -p 8080:8080 --env-file .env -e APP_ENV=development netraksha
# Cloud Run sets $PORT automatically (defaults to 8080); health probe: GET /api/health.

# ---------------------------------------------------------------------------
# Stage 1 — frontend builder (Vite 8 needs Node 20+; render.yaml pins 22.17.0)
# ---------------------------------------------------------------------------
FROM node:22-slim AS frontend-builder

WORKDIR /app/frontend

# Install first for better layer caching.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# Bakes canonical/SEO URLs into index.html + robots/sitemap (vite.config.js).
# For Cloud Run pass your run.app URL at build time; the API itself stays
# same-origin (/api) so VITE_API_BASE_URL is NOT needed for this deploy.
ARG VITE_SITE_URL=https://netraksha.xyz
ENV VITE_SITE_URL=${VITE_SITE_URL}
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 — Python runtime (CPU-only; InsightFace uses CPUExecutionProvider)
# ---------------------------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Cloud Run injects $PORT (8080). /tmp is the only writable dir, so
    # evidence must live there (ephemeral, same as Render free tier).
    PORT=8080 \
    TMPDIR=/tmp \
    SCREEN_EVIDENCE_DIR=/tmp/evidence

# System deps: tesseract-ocr (OCR/MRZ — without it OCR degrades to inconclusive
# + Yellow floor), libgl/libglib/libgomp for opencv/mediapipe/onnxruntime,
# fonts-dejavu-core for sample/specimen rendering + PIL default fonts.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    fonts-dejavu-core \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps first for layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App source. backend/app.py inserts the project root into sys.path and reads
# _PROJECT_ROOT/frontend/dist + pipeline/thresholds.json, so keep this layout.
COPY backend/ ./backend/
COPY pipeline/ ./pipeline/
COPY scripts/ ./scripts/
# Seed registry photos (samples/faces, ~56K): without these every citizen row
# resolves to registry_photo_missing_on_server and 3-way face stays partial.
# samples/evidence stays out via .dockerignore (runtime PII, not seed data).
COPY samples/faces/ ./samples/faces/

# Built SPA from stage 1 (served same-origin by the SPA fallback, must stay
# last route in backend/app.py).
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Runtime models: checks committed face_landmarker.task, provisions buffalo_l
# (~300MB) unless disabled. Never fail the build — the backend prewarms loudly
# at startup and degrades gracefully instead (same as build.sh).
ARG DISABLE_LOCAL_FACE_ENGINE=false
ENV DISABLE_LOCAL_FACE_ENGINE=${DISABLE_LOCAL_FACE_ENGINE}
RUN if [ "${DISABLE_LOCAL_FACE_ENGINE}" = "true" ]; then \
      echo "[docker] DISABLE_LOCAL_FACE_ENGINE=true — skipping model provisioning"; \
    else \
      bash scripts/setup_vendor.sh || true; \
    fi

# Writable dirs (Cloud Run filesystem is read-only except /tmp).
RUN mkdir -p /tmp/evidence samples/faces/uploads /tmp/netraksha_registry_photos 2>/dev/null || mkdir -p /tmp/evidence samples/faces/uploads

# Drop privileges: the app only needs /app (code+seeds, read) and /tmp (write).
RUN useradd -m -u 10001 appuser && chown -R appuser:appuser /app /tmp/evidence /tmp/netraksha_registry_photos
USER appuser

EXPOSE 8080

# Cloud Run health check: HTTP GET /api/health
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:${PORT:-8080}/api/health || exit 1

# Cloud Run health check: HTTP GET /api/health
# Use Python launcher so $PORT is read via os.environ — works even in exec form.
COPY start.py ./start.py
CMD ["python", "start.py"]
