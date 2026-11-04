#!/bin/bash
# ============================================================================================
#  ULTRON — instalação automática numa VM "Always Free" da Oracle Cloud (Ubuntu, ARM ou x86)
#  Cole este arquivo INTEIRO no campo "Script de inicialização" (cloud-init) ao criar a VM.
#  Antes de colar, preencha as 2 linhas abaixo.
# ============================================================================================
GITHUB_TOKEN="COLE_AQUI_SEU_TOKEN_DO_GITHUB"
SETUP_TOKEN="ESCOLHA_UMA_FRASE_SECRETA_PARA_O_PRIMEIRO_ACESSO"
# --------------------------------------------------------------------------------------------
BRANCH="ccr-39385a67-fi2gyu"
REPO="eduardostefani-20/ULTRON"
DIR="/opt/ultron"
# ============================================================================================

exec > >(tee -a /var/log/ultron-install.log) 2>&1
set -euo pipefail
echo "== ULTRON: instalação iniciada em $(date -u)"
case "$GITHUB_TOKEN" in
  COLE_AQUI*|"") echo "ERRO: preencha GITHUB_TOKEN no topo do script antes de criar a VM."; exit 1 ;;
esac
export DEBIAN_FRONTEND=noninteractive
APT="apt-get -o DPkg::Lock::Timeout=900 -y -q"

# 1. memória extra (swap) em máquinas pequenas — ajuda o build da interface
if [ "$(awk '/MemTotal/ {print $2}' /proc/meminfo)" -lt 6000000 ] && [ ! -f /swapfile ]; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

# 2. permite namespaces de usuário (isolamento de rede do sandbox do ULTRON)
if sysctl -n kernel.apparmor_restrict_unprivileged_userns >/dev/null 2>&1; then
  echo "kernel.apparmor_restrict_unprivileged_userns=0" > /etc/sysctl.d/60-ultron-userns.conf
  sysctl -q -p /etc/sysctl.d/60-ultron-userns.conf || true
fi

# 3. firewall da VM: libera HTTP/HTTPS (as imagens da Oracle só liberam SSH)
for port in 80 443; do
  iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null \
    || iptables -I INPUT 1 -p tcp --dport "$port" -m state --state NEW -j ACCEPT
done
if command -v netfilter-persistent >/dev/null 2>&1; then netfilter-persistent save || true; fi

# 4. git + Docker
$APT update
$APT install git curl ca-certificates cron openssl
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

# 5. código do ULTRON (o token não fica gravado no repositório)
AUTH="$(printf 'x-access-token:%s' "$GITHUB_TOKEN" | base64 -w0)"
if [ ! -d "$DIR/.git" ]; then
  git -c http.extraheader="AUTHORIZATION: basic $AUTH" clone --branch "$BRANCH" "https://github.com/$REPO.git" "$DIR"
fi

# 6. configuração (arquivo privado, só root lê)
IP="$(curl -fsS --max-time 10 https://api.ipify.org || curl -fsS --max-time 10 https://ifconfig.me || true)"
if ! [[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERRO: não foi possível descobrir o IP público da VM (ela tem IP público?)"; exit 1
fi
DOMAIN="${IP//./-}.sslip.io"
ENV_FILE="$DIR/deploy/oracle/.env"
if [ ! -f "$ENV_FILE" ]; then
  umask 077
  cat > "$ENV_FILE" <<CONF
ULTRON_ENV=production
ULTRON_DOMAIN=$DOMAIN
ULTRON_SECRET_KEY=$(openssl rand -hex 48)
ULTRON_SETUP_TOKEN=$SETUP_TOKEN
GITHUB_TOKEN=$GITHUB_TOKEN
ULTRON_GITHUB_REPO=$REPO
ULTRON_GIT_BASE_BRANCH=$BRANCH
ULTRON_MONTHLY_BUDGET_BRL=100
ULTRON_USD_BRL_RATE=5.50
CONF
fi

# 7. atualização automática (a cada 10 min e após reinícios) + primeira subida
cat > /etc/cron.d/ultron <<CRON
*/10 * * * * root $DIR/deploy/oracle/update.sh >> /var/log/ultron-update.log 2>&1
@reboot root sleep 90 && $DIR/deploy/oracle/update.sh >> /var/log/ultron-update.log 2>&1
CRON
chmod 644 /etc/cron.d/ultron
systemctl enable --now cron || true
ULTRON_FORCE=1 "$DIR/deploy/oracle/update.sh"

echo "== ULTRON pronto em https://$DOMAIN  ($(date -u))"
