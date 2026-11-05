#!/usr/bin/env bash
# Para o ULTRON (os dados continuam guardados):  ./scripts/parar.sh
# shellcheck source=scripts/comum.sh
. "$(dirname "$0")/comum.sh"
docker_pronto || { echo "O Docker não está rodando: o ULTRON já está parado."; exit 0; }
docker compose --profile celular down && echo "ULTRON parado. Seus dados continuam guardados; para ligar de novo: ./scripts/iniciar.sh"
