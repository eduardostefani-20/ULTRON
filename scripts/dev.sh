#!/usr/bin/env bash
# Desenvolvimento local: compila a interface e sobe o backend servindo tudo em http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")/.."
( cd frontend && npm install --no-audit --no-fund && npm run build )
cd backend
python3 -m venv .venv 2>/dev/null || true
. .venv/bin/activate
pip install -q -r requirements.txt && pip install -q --no-deps -e .
exec uvicorn ultron.main:app --reload --port 8000
