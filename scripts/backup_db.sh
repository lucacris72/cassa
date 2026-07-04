#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/cassa}"
ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/cassa}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

DATABASE_URL="${DATABASE_URL:-sqlite:///$APP_DIR/data/app.db}"
if [[ "$DATABASE_URL" != sqlite:///* ]]; then
  echo "Only sqlite DATABASE_URL backup is supported by this script: $DATABASE_URL" >&2
  exit 1
fi

DB_PATH="${DATABASE_URL#sqlite:///}"
if [[ "$DB_PATH" != /* ]]; then
  DB_PATH="$APP_DIR/$DB_PATH"
fi

if [[ ! -f "$DB_PATH" ]]; then
  echo "Database not found: $DB_PATH" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_FILE="$BACKUP_DIR/app-$STAMP.db"

sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"
gzip -f "$BACKUP_FILE"
find "$BACKUP_DIR" -type f -name 'app-*.db.gz' -mtime +"$RETENTION_DAYS" -delete

echo "$BACKUP_FILE.gz"
