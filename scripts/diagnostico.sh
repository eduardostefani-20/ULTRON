#!/usr/bin/env bash
# Diagnóstico remoto: ./scripts/diagnostico.sh https://seu-ultron.onrender.com
set -uo pipefail
URL="${1:?informe a URL do ULTRON}"
echo "== Saúde";            curl -fsS "$URL/api/health" && echo
echo "== Autenticação";     curl -fsS "$URL/api/auth/status" && echo
echo "== Interface";        curl -fsS -o /dev/null -w "HTTP %{http_code}\n" "$URL/"
echo "== Cabeçalhos";       curl -fsSI "$URL/" | grep -Ei "content-security-policy|x-frame-options" || true
echo "Para diagnóstico completo, no Shell da hospedagem: cd /app/backend && python -m ultron.doctor"
