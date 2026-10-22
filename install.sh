#!/usr/bin/env bash
set -euo pipefail
APP_DIR="/opt/cloudrun-telegram-bot"
SERVICE="cloudrun-telegram-bot"
BOT_USER="${SUDO_USER:-$USER}"

if [[ "$EUID" -ne 0 ]]; then
  echo "Lance avec : sudo bash install.sh"
  exit 1
fi

echo "=== Installation Cloud Run Telegram Deployer ==="
read -r -p "ID Telegram numérique autorisé : " TG_ID
[[ "$TG_ID" =~ ^[0-9]+$ ]] || { echo "ID Telegram invalide"; exit 1; }
read -r -s -p "Token du bot Telegram (@BotFather) : " TG_TOKEN; echo
[[ -n "$TG_TOKEN" ]] || { echo "Token vide"; exit 1; }
DEFAULT_IMAGE="docker.io/abess237/abess-ops1:latest"
read -r -p "Image Docker [$DEFAULT_IMAGE] : " IMAGE_INPUT
IMAGE="${IMAGE_INPUT:-$DEFAULT_IMAGE}"
read -r -p "Région Cloud Run [europe-west1] : " REGION_INPUT
REGION="${REGION_INPUT:-europe-west1}"
read -r -p "Autoriser l'accès public sans authentification ? (y/N) : " PUBLIC_INPUT
PUBLIC=false
[[ "$PUBLIC_INPUT" =~ ^[Yy]$ ]] && PUBLIC=true

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip curl ca-certificates gnupg apt-transport-https
if ! command -v gcloud >/dev/null 2>&1; then
  install -d -m 0755 /usr/share/keyrings
  curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
  chmod 0644 /usr/share/keyrings/cloud.google.gpg
  echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" > /etc/apt/sources.list.d/google-cloud-sdk.list
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y google-cloud-cli
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$APP_DIR"
cp -r "$SCRIPT_DIR/bot" "$APP_DIR/"
find "$APP_DIR/bot" -type d -name __pycache__ -prune -exec rm -rf {} +
cp "$SCRIPT_DIR/requirements.txt" "$APP_DIR/"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
cat > "$APP_DIR/.env" <<ENVVARS
TELEGRAM_BOT_TOKEN=$TG_TOKEN
ALLOWED_TELEGRAM_USER_IDS=$TG_ID
DEFAULT_IMAGE=$IMAGE
DEFAULT_REGION=$REGION
SERVICE_NAME_PREFIX=abess-run
ALLOW_UNAUTHENTICATED=$PUBLIC
GCLOUD_BIN=/usr/bin/gcloud
DEPLOY_TIMEOUT_SECONDS=900
ENVVARS
chmod 600 "$APP_DIR/.env"
chown -R "$BOT_USER":"$(id -gn "$BOT_USER")" "$APP_DIR"
HOME_DIR="$(getent passwd "$BOT_USER" | cut -d: -f6)"
cat > "/etc/systemd/system/$SERVICE.service" <<UNIT
[Unit]
Description=Cloud Run Telegram Deployer
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$BOT_USER
WorkingDirectory=$APP_DIR
Environment=HOME=$HOME_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/python -m bot.main
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now "$SERVICE"
echo
echo "Installation terminée. Le bot est en ligne et attend un lien sur Telegram."
echo "Statut : sudo systemctl status $SERVICE"
echo "Logs : sudo journalctl -u $SERVICE -f"
echo
echo "IMPORTANT : le token Telegram et l'ID Telegram ne donnent pas accès à Google Cloud."
echo "Le VPS doit disposer d'une identité gcloud autorisée sur le projet du laboratoire."
echo "Vérifie avec : sudo -u $BOT_USER gcloud auth list"
echo "Authentification interactive possible : sudo -u $BOT_USER gcloud auth login --no-launch-browser"
echo "Le bot n'utilise pas le token du lien Skills Boost et ne contourne pas les restrictions du lab."
