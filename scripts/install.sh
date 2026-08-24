#!/usr/bin/env bash
# Mirza rewrite installer - parity for install.sh (Apache/PHP/MySQL stack
# replaced by Python-native stack: systemd + uv + Caddy).
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "run as root"; exit 1; fi

APP_DIR=${APP_DIR:-/opt/mirza}
SERVICE_USER=${SERVICE_USER:-mirza}
DOMAIN=${1:?usage: install.sh <domain> (env: BOT_TOKEN, ADMIN_ID, DB_URL)}

echo "── Mirza installer ──────────────────────────────"

# 1. system packages
apt-get update -qq
apt-get install -y -qq python3 python3-venv curl caddy >/dev/null

# 2. app user + directory
id -u "$SERVICE_USER" &>/dev/null || useradd -r -m -s /usr/sbin/nologin "$SERVICE_USER"
mkdir -p "$APP_DIR"
cp -r . "$APP_DIR/"
cd "$APP_DIR"

# 3. venv + deps (uv if present, else pip)
if command -v uv >/dev/null; then
  sudo -u "$SERVICE_USER" uv venv .venv && \
  sudo -u "$SERVICE_USER" uv pip install --python .venv/bin/python .
else
  python3 -m venv .venv
  .venv/bin/pip install --quiet .
fi

# 4. env file
if [[ ! -f .env ]]; then
  cat > .env <<ENV
MIRZA_API_KEY=${BOT_TOKEN:?set BOT_TOKEN}
MIRZA_ADMIN_NUMBER=${ADMIN_ID:?set ADMIN_ID}
MIRZA_DOMAIN_HOSTS=$DOMAIN
MIRZA_DATABASE_URL=${DB_URL:-postgresql+asyncpg://mirza:mirza@localhost/mirza}
MIRZA_WEBHOOK_SECRET=$(openssl rand -hex 24)
MIRZA_SESSION_SECRET=$(openssl rand -hex 24)
ENV
  chmod 600 .env && chown "$SERVICE_USER" .env
fi

# 5. migrations
sudo -u "$SERVICE_USER" .venv/bin/alembic upgrade head

# 6. systemd service (web + webhook + scheduler)
cat > /etc/systemd/system/mirza.service <<UNIT
[Unit]
Description=Mirza Bot platform
After=network-online.target postgresql.service

[Service]
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python -m mirza.server
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now mirza

# 7. register Telegram webhook with secret
SECRET=$(grep MIRZA_WEBHOOK_SECRET .env | cut -d= -f2)
TOKEN=$(grep MIRZA_API_KEY .env | cut -d= -f2)
curl -s "https://api.telegram.org/bot$TOKEN/setWebhook" \
  -d "url=https://$DOMAIN/webhook" -d "secret_token=$SECRET" | grep -q '"ok":true' \
  && echo "✅ webhook registered" || echo "⚠️ webhook registration failed"

# 8. reverse proxy via Caddy (auto-HTTPS)
cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
    reverse_proxy 127.0.0.1:8080
}
CADDY
systemctl reload caddy 2>/dev/null || systemctl restart caddy

echo "✅ done → https://$DOMAIN"
