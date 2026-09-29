














FROM node:22-slim AS frontend-builder

WORKDIR /app/frontend


COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./



ARG VITE_SITE_URL=https://netraksha.xyz
ENV VITE_SITE_URL=${VITE_SITE_URL}
RUN npm run build




FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \


    PORT=8080 \
    SCREEN_EVIDENCE_DIR=/tmp/evidence



RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app


COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt



COPY backend/ ./backend/
COPY pipeline/ ./pipeline/
COPY scripts/ ./scripts/



COPY --from=frontend-builder /app/frontend/dist ./frontend/dist




ARG DISABLE_LOCAL_FACE_ENGINE=false
ENV DISABLE_LOCAL_FACE_ENGINE=${DISABLE_LOCAL_FACE_ENGINE}
RUN if [ "${DISABLE_LOCAL_FACE_ENGINE}" = "true" ]; then \
      echo "[docker] DISABLE_LOCAL_FACE_ENGINE=true — skipping model provisioning"; \
    else \
      bash scripts/setup_vendor.sh || true; \
    fi


RUN mkdir -p /tmp/evidence samples/faces/uploads $TMPDIR/netraksha_registry_photos 2>/dev/null || mkdir -p /tmp/evidence samples/faces/uploads

EXPOSE 8080



COPY start.py ./start.py
CMD ["python", "start.py"]
