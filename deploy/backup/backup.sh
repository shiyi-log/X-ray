#!/usr/bin/env sh
set -eu
umask 077

script_dir=$(unset CDPATH; cd -- "$(dirname -- "$0")" && pwd -P)
root_dir=$(unset CDPATH; cd -- "$script_dir/../.." && pwd -P)
# shellcheck source=deploy/scripts/release-lib.sh
. "$root_dir/deploy/scripts/release-lib.sh"

usage() {
  echo "usage: backup.sh --destination <directory> --config <env-file>" >&2
  exit 2
}

destination=
config_path=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --destination) [ "$#" -ge 2 ] || usage; destination=$2; shift 2 ;;
    --config) [ "$#" -ge 2 ] || usage; config_path=$2; shift 2 ;;
    *) usage ;;
  esac
done
if [ -z "$destination" ] || [ -z "$config_path" ]; then usage; fi
case "$destination" in /*) ;; *) die "backup destination must be absolute" ;; esac
case "$destination" in /|/var|/var/lib) die "backup destination is too broad" ;; esac

config_path=$(absolute_file "$config_path")
mkdir -p "$destination"
chmod 0700 "$destination"

db_service=$(require_config_value XRAY_BACKUP_DB_SERVICE "$config_path")
database_name=$(require_config_value XRAY_BACKUP_DATABASE_NAME "$config_path")
pg_service_file=$(absolute_file "$(require_config_value XRAY_BACKUP_PG_SERVICE_FILE "$config_path")")
pgpass_file=$(absolute_file "$(require_config_value XRAY_BACKUP_PGPASS_FILE "$config_path")")
recipient_file=$(absolute_file "$(require_config_value XRAY_BACKUP_AGE_RECIPIENT_FILE "$config_path")")
security_ledger=$(absolute_file "$(require_config_value XRAY_SECURITY_LEDGER_SNAPSHOT_FILE "$config_path")")
backend_image=$(require_config_value XRAY_BACKEND_IMAGE "$config_path")
frontend_image=$(require_config_value XRAY_FRONTEND_IMAGE "$config_path")
control_key_version=$(require_config_value XRAY_CONTROL_KEY_VERSION "$config_path")
subscription_key_version=$(require_config_value XRAY_SUBSCRIPTION_KEY_VERSION "$config_path")

printf '%s' "$database_name" | grep -Eq '^[A-Za-z_][A-Za-z0-9_]{0,62}$' \
  || die "invalid backup database name"
printf '%s' "$backend_image" | grep -Eq '@sha256:[0-9a-f]{64}$' \
  || die "backend image must be immutable"
printf '%s' "$frontend_image" | grep -Eq '@sha256:[0-9a-f]{64}$' \
  || die "frontend image must be immutable"
printf '%s' "$control_key_version" | grep -Eq '^[1-9][0-9]*$' \
  || die "invalid control key version"
printf '%s' "$subscription_key_version" | grep -Eq '^[1-9][0-9]*$' \
  || die "invalid subscription key version"
case "$(file_mode "$pgpass_file")" in 400|600) ;; *) die "pgpass file must be 0400 or 0600" ;; esac

pg_dump --version | grep -Fq "17.6" || die "pg_dump 17.6 is required"
age --version 2>&1 | grep -Fq "1.2.1" || die "age 1.2.1 is required"
jq --version | grep -Fq "jq-1.8.1" || die "jq 1.8.1 is required"

recipient=$(sed -n '1p' "$recipient_file")
printf '%s' "$recipient" | grep -Eq '^age1[0-9a-z]{58}$' \
  || die "invalid age recipient"
security_sequence=$(jq -er '.expected_sequence | select(type == "number" and . >= 0)' "$security_ledger") \
  || die "security ledger snapshot is invalid"
security_sha=$(sha256_file "$security_ledger")
app_version=$(tr -d '\r\n' <"$root_dir/VERSION")
installer_sha=$(sha256_file "$root_dir/installer/manifest.json")
created_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
stamp=$(date -u '+%Y%m%dT%H%M%SZ')
backup_name="xray-${app_version}-${stamp}-$$"
final_dir="$destination/$backup_name"
incoming_dir="$destination/.incoming-$backup_name"
if [ -e "$final_dir" ] || [ -e "$incoming_dir" ]; then
  die "backup destination already exists"
fi

temp_dir=$(mktemp -d "${TMPDIR:-/tmp}/xray-backup.XXXXXX")
cleanup() { rm -rf -- "$temp_dir" "$incoming_dir"; }
trap cleanup EXIT HUP INT TERM

PGSERVICEFILE=$pg_service_file PGPASSFILE=$pgpass_file \
  pg_dump --format=custom --no-owner --no-acl \
  --file="$temp_dir/database.dump" "service=$db_service"
chmod 0600 "$temp_dir/database.dump"
plaintext_sha=$(sha256_file "$temp_dir/database.dump")
age -r "$recipient" -o "$temp_dir/database.dump.age" "$temp_dir/database.dump"
encrypted_sha=$(sha256_file "$temp_dir/database.dump.age")

mkdir "$incoming_dir"
install -m 0600 "$temp_dir/database.dump.age" "$incoming_dir/database.dump.age"
jq -n \
  --arg app_version "$app_version" \
  --arg created_at "$created_at" \
  --arg database_name "$database_name" \
  --arg encrypted_sha "$encrypted_sha" \
  --arg plaintext_sha "$plaintext_sha" \
  --arg security_sha "$security_sha" \
  --arg backend_image "$backend_image" \
  --arg frontend_image "$frontend_image" \
  --arg installer_sha "$installer_sha" \
  --argjson security_sequence "$security_sequence" \
  --argjson control_key_version "$control_key_version" \
  --argjson subscription_key_version "$subscription_key_version" \
  '{schema_version: 1, app_version: $app_version, created_at: $created_at,
    database_name: $database_name, encrypted_dump: "database.dump.age",
    encrypted_sha256: $encrypted_sha, plaintext_sha256: $plaintext_sha,
    security_ledger_sequence: $security_sequence,
    security_ledger_sha256: $security_sha, backend_image: $backend_image,
    frontend_image: $frontend_image, installer_manifest_sha256: $installer_sha,
    control_key_version: $control_key_version,
    subscription_key_version: $subscription_key_version}' \
  >"$incoming_dir/manifest.json"
chmod 0600 "$incoming_dir/manifest.json"
sync "$incoming_dir/database.dump.age" "$incoming_dir/manifest.json"
mv "$incoming_dir" "$final_dir"
trap - EXIT HUP INT TERM
rm -rf -- "$temp_dir"
echo "$final_dir"
