#!/usr/bin/env sh
set -eu

script_dir=$(unset CDPATH; cd -- "$(dirname -- "$0")" && pwd -P)
# shellcheck source=deploy/scripts/release-lib.sh
. "$script_dir/release-lib.sh"

usage() {
  echo "usage: preflight.sh --config <env-file> [--compose <compose-file>]" >&2
  exit 2
}

config_path=
compose_path="$script_dir/../compose/production.yml"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --config) [ "$#" -ge 2 ] || usage; config_path=$2; shift 2 ;;
    --compose) [ "$#" -ge 2 ] || usage; compose_path=$2; shift 2 ;;
    *) usage ;;
  esac
done
[ -n "$config_path" ] || usage

XRAY_RELEASE_CONFIG=$(absolute_file "$config_path")
XRAY_RELEASE_COMPOSE=$(absolute_file "$compose_path")
export XRAY_RELEASE_CONFIG XRAY_RELEASE_COMPOSE

required_values='XRAY_ADMIN_HOST XRAY_ADMIN_ALLOW_CIDR XRAY_ADMIN_BIND_IP
XRAY_SUBSCRIPTION_HOST XRAY_SUBSCRIPTION_BIND_IP XRAY_DATABASE_NAME
XRAY_BACKEND_IMAGE XRAY_FRONTEND_IMAGE XRAY_BACKUP_TOOLS_IMAGE
XRAY_BACKUP_DOCKER_NETWORK XRAY_RELEASE_BACKUP_DESTINATION XRAY_BACKUP_DB_SERVICE
XRAY_BACKUP_DATABASE_NAME XRAY_BACKUP_PG_SERVICE_FILE
XRAY_BACKUP_PGPASS_FILE XRAY_BACKUP_AGE_RECIPIENT_FILE
XRAY_SECURITY_LEDGER_HOST_DIR XRAY_SECURITY_LEDGER_SNAPSHOT_FILE
XRAY_RECOVERY_EVIDENCE_DIR XRAY_CONTROL_KEY_VERSION
XRAY_SUBSCRIPTION_KEY_VERSION'
for key in $required_values; do
  value=$(require_config_value "$key" "$XRAY_RELEASE_CONFIG")
  case "$key" in
    XRAY_ADMIN_HOST|XRAY_SUBSCRIPTION_HOST)
      printf '%s' "$value" | grep -Eq '^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$' \
        || die "invalid hostname in $key"
      ;;
    XRAY_BACKEND_IMAGE|XRAY_FRONTEND_IMAGE|XRAY_BACKUP_TOOLS_IMAGE)
      printf '%s' "$value" | grep -Eq '@sha256:[0-9a-f]{64}$' \
        || die "$key must use an immutable sha256 image digest"
      ;;
  esac
done

secret_keys='XRAY_DJANGO_SECRET_KEY_FILE XRAY_CONTROL_MASTER_KEY_FILE
XRAY_SUBSCRIPTION_MASTER_KEY_FILE XRAY_OWNER_DB_PASSWORD_FILE
XRAY_ADMIN_DB_PASSWORD_FILE XRAY_SUBSCRIPTION_DB_PASSWORD_FILE
XRAY_WORKER_DB_PASSWORD_FILE XRAY_OUTBOX_DB_PASSWORD_FILE
XRAY_CLOUD_CREDENTIALS_FILE XRAY_ADMIN_TLS_KEY_FILE
XRAY_SUBSCRIPTION_TLS_KEY_FILE XRAY_BACKUP_PGPASS_FILE'
public_file_keys='XRAY_ADMIN_TLS_CERT_FILE XRAY_SUBSCRIPTION_TLS_CERT_FILE
XRAY_BACKUP_PG_SERVICE_FILE XRAY_BACKUP_AGE_RECIPIENT_FILE
XRAY_SECURITY_LEDGER_SNAPSHOT_FILE'

for key in $secret_keys $public_file_keys; do
  path=$(require_config_value "$key" "$XRAY_RELEASE_CONFIG")
  case "$path" in /*) ;; *) die "$key must be an absolute path" ;; esac
  [ -r "$path" ] || die "$key is not readable"
  [ -s "$path" ] || die "$key is empty"
done

for key in XRAY_RELEASE_BACKUP_DESTINATION XRAY_SECURITY_LEDGER_HOST_DIR XRAY_RECOVERY_EVIDENCE_DIR; do
  path=$(require_config_value "$key" "$XRAY_RELEASE_CONFIG")
  case "$path" in /*) ;; *) die "$key must be an absolute path" ;; esac
  [ -d "$path" ] || die "$key is not a directory"
  [ -w "$path" ] || die "$key is not writable"
done

for key in $secret_keys; do
  path=$(require_config_value "$key" "$XRAY_RELEASE_CONFIG")
  mode=$(file_mode "$path")
  case "$mode" in
    400|440|600|640) ;;
    *) die "$key must not be readable by other users (found mode $mode)" ;;
  esac
done

command -v docker >/dev/null 2>&1 || die "docker is required"
docker compose version >/dev/null 2>&1 || die "docker compose is required"
compose config --quiet

echo "preflight passed for $(basename "$XRAY_RELEASE_COMPOSE")"
