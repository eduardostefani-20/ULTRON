#!/bin/bash
# Atualizador do ULTRON na VM: busca o branch no GitHub e, se mudou (ex.: uma melhoria aprovada e
# publicada pelo próprio ULTRON), reconstrói e reinicia. Se o build falhar, a versão atual continua no ar.
set -uo pipefail
DIR="${ULTRON_DIR:-/opt/ultron}"
COMPOSE="docker compose -f $DIR/deploy/oracle/docker-compose.yml"
exec 9>"${ULTRON_LOCK:-/var/lock/ultron-update.lock}"
flock -n 9 || exit 0
cd "$DIR" || exit 1
set -a
# shellcheck disable=SC1091
. "$DIR/deploy/oracle/.env"
set +a
BRANCH="${ULTRON_GIT_BASE_BRANCH:?ULTRON_GIT_BASE_BRANCH ausente}"

# firewall da VM: HTTP/HTTPS liberados (reaplicado após reinícios)
for port in 80 443; do
  iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null \
    || iptables -I INPUT 1 -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null || true
done

# containers não acessam o serviço de metadados da nuvem (HTTP), só o DNS
if iptables -L DOCKER-USER -n >/dev/null 2>&1; then
  for port in 80 443; do
    iptables -C DOCKER-USER -d 169.254.169.254 -p tcp --dport "$port" -j DROP 2>/dev/null \
      || iptables -I DOCKER-USER -d 169.254.169.254 -p tcp --dport "$port" -j DROP
  done
fi

# token vigente: o salvo no app (Integrações → GitHub); o do .env é só reserva
APP_TOKEN="$($COMPOSE exec -T ultron python -m ultron.admin github-token 2>/dev/null || true)"
TOKEN="${APP_TOKEN:-${GITHUB_TOKEN:-}}"
AUTH="$(printf 'x-access-token:%s' "$TOKEN" | base64 -w0)"
if ! git -c http.extraheader="AUTHORIZATION: basic $AUTH" fetch -q origin "$BRANCH"; then
  echo "$(date -u) falha ao buscar o GitHub (token expirado?)"
  exit 1
fi
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"
RUNNING="$($COMPOSE ps --status running --services 2>/dev/null | grep -c '^ultron$' || true)"
if [ "$LOCAL" = "$REMOTE" ] && [ "$RUNNING" -ge 1 ] && [ -z "${ULTRON_FORCE:-}" ]; then
  exit 0
fi
echo "$(date -u) implantando ${REMOTE:0:10} (antes ${LOCAL:0:10})"
git reset -q --hard "origin/$BRANCH"
if $COMPOSE up -d --build --remove-orphans; then
  docker image prune -f >/dev/null 2>&1 || true
  echo "$(date -u) ULTRON no ar com ${REMOTE:0:10}"
else
  echo "$(date -u) build falhou — mantendo a versão anterior em execução"
  exit 1
fi
