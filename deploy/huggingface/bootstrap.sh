#!/bin/bash
# Baixa o ULTRON do GitHub (privado), compila a interface e inicia o servidor.
# Executado a cada início do Space; o token nunca é gravado em disco.
set -euo pipefail
: "${GITHUB_TOKEN:?defina o segredo GITHUB_TOKEN no Space}"
: "${ULTRON_GITHUB_REPO:?defina o segredo ULTRON_GITHUB_REPO no Space}"
: "${ULTRON_GIT_BASE_BRANCH:?defina o segredo ULTRON_GIT_BASE_BRANCH no Space}"
: "${DATABASE_URL:?defina o segredo DATABASE_URL (Supabase) no Space}"
APP="${ULTRON_APP_DIR:-/tmp/ultron-app}"
SOURCE="${ULTRON_BOOTSTRAP_SOURCE:-https://github.com/$ULTRON_GITHUB_REPO.git}"
mkdir -p "$HOME" /tmp/ultron-data
export npm_config_cache=/tmp/npm-cache PIP_USER=1 PYTHONUSERBASE=/tmp/pyuser
echo "[bootstrap] baixando $ULTRON_GITHUB_REPO@$ULTRON_GIT_BASE_BRANCH"
rm -rf "$APP"
AUTH="$(printf 'x-access-token:%s' "$GITHUB_TOKEN" | base64 -w0)"
git -c http.extraheader="AUTHORIZATION: basic $AUTH" clone -q --depth 1 --branch "$ULTRON_GIT_BASE_BRANCH" "$SOURCE" "$APP"
echo "[bootstrap] dependências (somente se mudaram)"
pip install -q --no-cache-dir -r "$APP/backend/requirements.txt" || echo "[bootstrap] aviso: falha ao atualizar dependências"
echo "[bootstrap] compilando a interface"
(cd "$APP/frontend" && npm ci --no-audit --no-fund --loglevel=error && NEXT_TELEMETRY_DISABLED=1 npm run build >/dev/null)
export PYTHONPATH="$APP/backend:/tmp/pyuser/lib/python3.13/site-packages"
export ULTRON_FRONTEND_DIR="$APP/frontend/out" ULTRON_REPO_SOURCE_DIR="$APP" ULTRON_DATA_DIR=/tmp/ultron-data
cd "$APP/backend"
echo "[bootstrap] iniciando o ULTRON"
exec python -m uvicorn ultron.main:app --host 0.0.0.0 --port "${PORT:-7860}" --proxy-headers --forwarded-allow-ips='*'
