# tax.ng production image: one process serves the API and the built frontend
# (backend/taxng/api/app.py mounts frontend/dist), so the strict same-origin
# CSP and cookie sign-in work without a proxy layer.

# ---- Stage 1: build the frontend bundles ----
FROM node:22-slim AS web
WORKDIR /srv/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python runtime ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv/backend \
    TAXNG_DATA_DIR=/data \
    TAXNG_DEMO=0
WORKDIR /srv

RUN pip install --no-cache-dir "starlette>=0.37" "uvicorn>=0.29" "pyyaml>=6.0"

# Keep the repo layout: config.py resolves rules/, content/ and frontend/dist
# relative to the repo root, and the SQL schemas live inside the package.
COPY backend/taxng /srv/backend/taxng
COPY rules /srv/rules
COPY content /srv/content
COPY --from=web /srv/frontend/dist /srv/frontend/dist

RUN useradd --create-home --uid 10001 taxng && mkdir -p /data && chown taxng /data
USER taxng

EXPOSE 8080
WORKDIR /srv/backend
CMD ["python", "-m", "taxng", "serve", "--host", "0.0.0.0", "--port", "8080"]
