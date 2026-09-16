#!/usr/bin/env sh
set -eu

read_secret() {
  name=$1
  path=$2
  [ -r "$path" ] || { echo "required database secret is unavailable" >&2; exit 1; }
  value=$(tr -d '\r\n' <"$path")
  [ -n "$value" ] || { echo "required database secret is empty" >&2; exit 1; }
  export "$name=$value"
  unset value
}

read_secret PGPASSWORD /run/secrets/owner_db_password
read_secret XRAY_ADMIN_DB_PASSWORD /run/secrets/admin_db_password
read_secret XRAY_SUBSCRIPTION_DB_PASSWORD /run/secrets/subscription_db_password
read_secret XRAY_WORKER_DB_PASSWORD /run/secrets/worker_db_password
read_secret XRAY_OUTBOX_DB_PASSWORD /run/secrets/outbox_db_password

psql --no-password --set ON_ERROR_STOP=1 \
  --host "$XRAY_DATABASE_HOST" \
  --port "${XRAY_DATABASE_PORT:-5432}" \
  --username xray_owner \
  --dbname "$XRAY_DATABASE_NAME" \
  --file /opt/xray/roles.sql

unset PGPASSWORD XRAY_ADMIN_DB_PASSWORD XRAY_SUBSCRIPTION_DB_PASSWORD \
  XRAY_WORKER_DB_PASSWORD XRAY_OUTBOX_DB_PASSWORD
