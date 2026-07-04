#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/cassa}"
SERVICE_NAME="${SERVICE_NAME:-cassa}"
ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"

cd "$APP_DIR"

if [[ -x "$APP_DIR/scripts/backup_db.sh" ]]; then
  "$APP_DIR/scripts/backup_db.sh"
fi

git fetch --all --prune
git pull --ff-only

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

sudo -n systemctl restart "$SERVICE_NAME"
sudo -n systemctl --no-pager --full status "$SERVICE_NAME"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

curl -fsS "http://${APP_HOST:-127.0.0.1}:${APP_PORT:-8000}/healthz"
echo
