#!/usr/bin/env sh
set -eu
umask 077

script_dir=$(unset CDPATH; cd -- "$(dirname -- "$0")" && pwd -P)
root_dir=$(unset CDPATH; cd -- "$script_dir/../.." && pwd -P)
# shellcheck source=deploy/scripts/release-lib.sh
. "$root_dir/deploy/scripts/release-lib.sh"

usage() {
  echo "usage: restore.sh --backup <directory> --target <xray_restore_name> --config <env-file> [--identity <file>]" >&2
  exit 2
}

backup_dir=
target=
config_path=
identity=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --backup) [ "$#" -ge 2 ] || usage; backup_dir=$2; shift 2 ;;
    --target) [ "$#" -ge 2 ] || usage; target=$2; shift 2 ;;
    --config) [ "$#" -ge 2 ] || usage; config_path=$2; shift 2 ;;
    --identity) [ "$#" -ge 2 ] || usage; identity=$2; shift 2 ;;
    *) usage ;;
  esac
done
if [ -z "$backup_dir" ] || [ -z "$target" ] || [ -z "$config_path" ]; then usage; fi
printf '%s' "$target" | grep -Eq '^xray_restore_[A-Za-z0-9_]+$' \
  || die "restore target must start with xray_restore_ and contain only safe characters"

config_path=$(absolute_file "$config_path")
backup_dir=$(unset CDPATH; cd -- "$backup_dir" 2>/dev/null && pwd -P) \
  || die "backup directory is unavailable"
admin_service=$(require_config_value XRAY_RESTORE_ADMIN_SERVICE "$config_path")
pg_service_file=$(absolute_file "$(require_config_value XRAY_BACKUP_PG_SERVICE_FILE "$config_path")")
pgpass_file=$(absolute_file "$(require_config_value XRAY_BACKUP_PGPASS_FILE "$config_path")")
evidence_dir=$(require_config_value XRAY_RECOVERY_EVIDENCE_DIR "$config_path")
if [ -z "$identity" ]; then
  identity=$(require_config_value XRAY_BACKUP_AGE_IDENTITY_FILE "$config_path")
fi
identity=$(absolute_file "$identity")
case "$evidence_dir" in /*) ;; *) die "recovery evidence directory must be absolute" ;; esac
mkdir -p "$evidence_dir"
chmod 0700 "$evidence_dir"
case "$(file_mode "$pgpass_file")" in 400|600) ;; *) die "pgpass file must be 0400 or 0600" ;; esac

"$script_dir/verify.sh" --backup "$backup_dir" --identity "$identity"
manifest="$backup_dir/manifest.json"
started_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
started_epoch=$(date +%s)

exists=$(PGSERVICEFILE=$pg_service_file PGPASSFILE=$pgpass_file \
  psql --no-password --tuples-only --no-align \
  --dbname="service=$admin_service dbname=postgres" \
  --set="target=$target" \
  --command="SELECT 1 FROM pg_database WHERE datname = :'target'" | tr -d '[:space:]')
[ -z "$exists" ] || die "restore target already exists"

PGSERVICEFILE=$pg_service_file PGPASSFILE=$pgpass_file \
  createdb --maintenance-db="service=$admin_service dbname=postgres" "$target"

temp_dir=$(mktemp -d "${TMPDIR:-/tmp}/xray-restore.XXXXXX")
cleanup() { rm -rf -- "$temp_dir"; }
trap cleanup EXIT HUP INT TERM
age --decrypt -i "$identity" -o "$temp_dir/database.dump" \
  "$backup_dir/database.dump.age"
PGSERVICEFILE=$pg_service_file PGPASSFILE=$pgpass_file \
  pg_restore --exit-on-error --no-owner --no-acl \
  --dbname="service=$admin_service dbname=$target" "$temp_dir/database.dump"
PGSERVICEFILE=$pg_service_file PGPASSFILE=$pgpass_file \
  psql --no-password --dbname="service=$admin_service dbname=$target" \
  --file "$script_dir/lockdown.sql" >/dev/null

completed_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
completed_epoch=$(date +%s)
duration_seconds=$((completed_epoch - started_epoch))
manifest_sha=$(sha256_file "$manifest")
receipt="$evidence_dir/restore-${target}-${completed_epoch}.json"
jq -n \
  --arg target "$target" \
  --arg started_at "$started_at" \
  --arg completed_at "$completed_at" \
  --arg manifest_sha "$manifest_sha" \
  --argjson duration_seconds "$duration_seconds" \
  '{schema_version: 1, target_database: $target, started_at: $started_at,
    completed_at: $completed_at, duration_seconds: $duration_seconds,
    backup_manifest_sha256: $manifest_sha, security_mode: "MAINTENANCE",
    network_mode: "isolated", requires_manual_reopen: true}' >"$receipt"
chmod 0600 "$receipt"
echo "$receipt"
