#!/usr/bin/env sh
set -eu

read_secret() {
  variable_name=$1
  secret_path=$2
  if [ ! -r "$secret_path" ]; then
    echo "required secret file is unavailable: $secret_path" >&2
    exit 1
  fi
  secret_value=$(tr -d '\r\n' <"$secret_path")
  if [ -z "$secret_value" ]; then
    echo "required secret file is empty: $secret_path" >&2
    exit 1
  fi
  export "$variable_name=$secret_value"
  unset secret_value
}

[ ! -e /run/secrets/django_secret_key ] || read_secret XRAY_SECRET_KEY /run/secrets/django_secret_key
[ ! -e /run/secrets/control_master_key ] || read_secret XRAY_CONTROL_MASTER_KEY /run/secrets/control_master_key
[ ! -e /run/secrets/subscription_master_key ] || read_secret XRAY_SUBSCRIPTION_MASTER_KEY /run/secrets/subscription_master_key

if [ -n "${XRAY_DATABASE_PASSWORD_FILE:-}" ]; then
  read_secret XRAY_DATABASE_PASSWORD "$XRAY_DATABASE_PASSWORD_FILE"
  XRAY_DATABASE_URL=$(python - <<'PY'
import os
from urllib.parse import quote

user = quote(os.environ["XRAY_DATABASE_USER"], safe="")
password = quote(os.environ["XRAY_DATABASE_PASSWORD"], safe="")
host = os.environ["XRAY_DATABASE_HOST"]
port = os.environ.get("XRAY_DATABASE_PORT", "5432")
name = quote(os.environ["XRAY_DATABASE_NAME"], safe="")
print(f"postgresql://{user}:{password}@{host}:{port}/{name}")
PY
  )
  export XRAY_DATABASE_URL
  unset XRAY_DATABASE_PASSWORD
fi

if [ -e /run/secrets/cloud_credentials ]; then
  export XRAY_CLOUD_CREDENTIALS_FILE=/run/secrets/cloud_credentials
fi

exec "$@"
