#!/usr/bin/env bash
# Baixa a versão mais recente do ULTRON do seu GitHub (incluindo melhorias aprovadas que o próprio ULTRON
# publicou) e reinicia. Se a construção falhar, a versão atual continua funcionando.  ./scripts/atualizar.sh
set -uo pipefail
# o corpo inteiro é lido antes de executar: a atualização pode substituir este próprio arquivo
main() {
  # shellcheck source=scripts/comum.sh
  . "$(dirname "$0")/comum.sh"
  echo "=== ULTRON: atualizar ==="
  garantir_docker
  local repo branch token sha atual src d api
  repo="$(ler_env ULTRON_GITHUB_REPO)"; branch="$(ler_env ULTRON_GIT_BASE_BRANCH)"
  [ -n "$repo" ] && [ -n "$branch" ] || { echo "Rode ./scripts/iniciar.sh primeiro (falta o arquivo .env)."; exit 1; }
  api="${ULTRON_GITHUB_API:-https://api.github.com}"
  # token vigente: o salvo no app (Integrações → GitHub), lido de dentro do ULTRON; nunca é gravado em disco
  token="$(docker compose exec -T ultron python -m ultron.admin github-token 2>/dev/null | tr -d '\r\n')"
  [ -n "$token" ] || { echo "Para atualizar, o ULTRON precisa estar ligado e com o token do GitHub salvo em Integrações → GitHub."; exit 1; }
  gh_api() { curl -fsSL -H "Authorization: Bearer $token" -H "User-Agent: ultron-atualizador" "$@"; }
  sha="$(gh_api -H "Accept: application/vnd.github.sha" "$api/repos/$repo/commits/$branch")" \
    || { echo "O GitHub recusou o acesso. Confira o token em Integrações."; exit 1; }
  atual="$(cat "$RAIZ/.versao" 2>/dev/null || true)"
  if [ "$sha" = "$atual" ]; then echo "Você já está na versão mais recente (${sha:0:7})."; exit 0; fi
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  echo "Baixando a versão ${sha:0:7}..."
  gh_api "$api/repos/$repo/tarball/$sha" | tar -xz -C "$tmp" || { echo "Falha ao baixar a atualização."; exit 1; }
  src="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)"
  [ -n "$src" ] && [ -f "$src/docker-compose.yml" ] || { echo "O pacote baixado não parece o ULTRON."; exit 1; }
  # pastas de código são espelhadas (sem tocar no .env nem nos dados, que ficam no Docker)
  for d in "$src"/* "$src"/.[!.]*; do
    [ -e "$d" ] || continue
    if [ -d "$d" ]; then rm -rf "${RAIZ:?}/$(basename "$d")"; cp -R "$d" "$RAIZ/"; else cp -f "$d" "$RAIZ/"; fi
  done
  echo "Reconstruindo o ULTRON (alguns minutos)..."
  docker compose up -d --build || { echo "A construção falhou: a versão anterior continua no ar. Tente de novo mais tarde."; exit 1; }
  echo "$sha" > "$RAIZ/.versao"
  aguardar_ultron && mostrar_enderecos
  exit 0
}
main "$@"
