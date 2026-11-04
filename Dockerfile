# ULTRON — imagem única: interface (Next.js estático) + API FastAPI + scheduler + sandbox.
# Funciona em Render, Railway, Fly.io, VPS ou qualquer hospedagem de contêineres.

# ---------- 1. interface
FROM node:22-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---------- 2. backend
FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ULTRON_ENV=production \
    ULTRON_DATA_DIR=/data \
    ULTRON_FRONTEND_DIR=/app/frontend/out \
    ULTRON_REPO_SOURCE_DIR=/app
# git: workspace de autoevolução · util-linux: unshare (isolamento de rede do sandbox)
RUN apt-get update && apt-get install -y --no-install-recommends git util-linux ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY backend/ backend/
RUN pip install --no-deps -e backend/
COPY --from=frontend /app/frontend/out /app/frontend/out
COPY docs/ docs/
COPY README.md ./
RUN mkdir -p /data && chmod 711 /data
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health')"
# uma única instância: o scheduler e o worker de missões rodam no mesmo processo
CMD ["sh", "-c", "uvicorn ultron.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
