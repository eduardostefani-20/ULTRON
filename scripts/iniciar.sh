#!/usr/bin/env bash
# Inicia o ULTRON neste computador (Mac/Linux):  ./scripts/iniciar.sh
# Guia: docs/INSTALACAO_NOTEBOOK.md
set -uo pipefail
# shellcheck source=scripts/comum.sh
. "$(dirname "$0")/comum.sh"

echo "=== ULTRON: iniciar ==="
garantir_docker
if [ ! -f "$ENV_FILE" ]; then
  umask 077
  cat > "$ENV_FILE" <<CONF
# Configuração do ULTRON neste computador (criada automaticamente). Não compartilhe este arquivo.
ULTRON_ENV=production
ULTRON_SECRET_KEY=$(segredo 32)
ULTRON_SETUP_TOKEN=$(segredo 8)
ULTRON_GITHUB_REPO=eduardostefani-20/ULTRON
ULTRON_GIT_BASE_BRANCH=ccr-39385a67-fi2gyu
ULTRON_MONTHLY_BUDGET_BRL=100
# Endereço HTTPS para usar no celular de qualquer lugar (apague a linha abaixo para usar só no Wi-Fi de casa)
COMPOSE_PROFILES=celular
# Opcional: banco no Supabase (vazio = dados guardados neste computador)
DATABASE_URL=
CONF
  echo "Configuração criada (arquivo .env)."
fi
echo "Construindo e iniciando o ULTRON. Na primeira vez leva de 5 a 15 minutos..."
docker compose up -d --build || { echo "Não foi possível iniciar. Veja a mensagem acima; se for falha de internet, rode de novo."; exit 1; }
aguardar_ultron || { echo "O ULTRON não respondeu a tempo. Veja os registros com: docker compose logs ultron"; exit 1; }
mostrar_enderecos
