#!/usr/bin/env bash
# Funções comuns dos scripts do ULTRON no Mac/Linux (usadas por iniciar.sh, atualizar.sh e parar.sh).
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ" || exit 1
ENV_FILE="$RAIZ/.env"
URL_LOCAL="${ULTRON_URL_LOCAL:-http://localhost:8000}"

ler_env() { [ -f "$ENV_FILE" ] && sed -n "s/^[[:space:]]*$1=//p" "$ENV_FILE" | tail -1 | tr -d '\r'; }
segredo() { openssl rand -hex "$1" 2>/dev/null || od -An -N"$1" -tx1 /dev/urandom | tr -d ' \n'; }
docker_pronto() { docker info >/dev/null 2>&1; }

garantir_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Instale o Docker Desktop (Mac) ou o Docker Engine (Linux): https://www.docker.com/products/docker-desktop/"
    exit 1
  fi
  docker_pronto && return 0
  [ "$(uname)" = "Darwin" ] && open -a Docker 2>/dev/null && echo "Abrindo o Docker Desktop..."
  echo "Aguardando o Docker ficar pronto (até 3 minutos)..."
  for _ in $(seq 1 90); do sleep 2; docker_pronto && return 0; done
  echo "O Docker não respondeu. Abra o Docker Desktop (no Linux: 'sudo systemctl start docker'; talvez seja"
  echo "preciso rodar este script com sudo ou adicionar seu usuário ao grupo docker) e tente de novo."
  exit 1
}

aguardar_ultron() {
  echo "Aguardando o ULTRON responder..."
  for _ in $(seq 1 90); do
    curl -fsS -m 5 "$URL_LOCAL/api/health" >/dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}

endereco_tunel() {
  case "$(ler_env COMPOSE_PROFILES)" in *celular*) ;; *) return 0 ;; esac
  for _ in $(seq 1 30); do
    url="$(docker compose logs tunnel 2>&1 | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1)"
    [ -n "$url" ] && { echo "$url"; return 0; }
    sleep 2
  done
}

mostrar_enderecos() {
  echo ""
  echo "ULTRON no ar!"
  echo "  Neste computador:            $URL_LOCAL"
  ip="$( (ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}') | head -1)"
  [ -n "$ip" ] && echo "  No celular (mesmo Wi-Fi):    http://$ip:8000"
  url="$(endereco_tunel)"
  if [ -n "$url" ]; then
    echo "  No celular (qualquer lugar): $url"
    echo "    O endereço muda quando o computador reinicia: o link e o QR code atuais aparecem na tela inicial do ULTRON."
    echo "$url" > "$RAIZ/ENDERECO-CELULAR.txt"
  fi
  tok="$(ler_env ULTRON_SETUP_TOKEN)"
  [ -n "$tok" ] && echo "  Token de configuração (só no primeiro acesso): $tok"
  return 0
}
