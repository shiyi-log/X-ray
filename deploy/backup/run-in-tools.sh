#!/usr/bin/env sh
set -eu

script_dir=$(unset CDPATH; cd -- "$(dirname -- "$0")" && pwd -P)
root_dir=$(unset CDPATH; cd -- "$script_dir/../.." && pwd -P)
# shellcheck source=deploy/scripts/release-lib.sh
. "$root_dir/deploy/scripts/release-lib.sh"

usage() {
  echo "usage: run-in-tools.sh --config <env-file> backup [arguments]" >&2
  exit 2
}

[ "$#" -ge 3 ] || usage
[ "$1" = "--config" ] || usage
config_path=$(absolute_file "$2")
action=$3
shift 3
[ "$action" = "backup" ] || usage

image=$(require_config_value XRAY_BACKUP_TOOLS_IMAGE "$config_path")
network=$(require_config_value XRAY_BACKUP_DOCKER_NETWORK "$config_path")
printf '%s' "$image" | grep -Eq '@sha256:[0-9a-f]{64}$' \
  || die "backup tools image must use an immutable digest"
printf '%s' "$network" | grep -Eq '^[A-Za-z0-9_.-]+$' \
  || die "invalid backup Docker network"
command -v docker >/dev/null 2>&1 || die "docker is required for backup tools"

pg_service=$(absolute_file "$(require_config_value XRAY_BACKUP_PG_SERVICE_FILE "$config_path")")
pgpass=$(absolute_file "$(require_config_value XRAY_BACKUP_PGPASS_FILE "$config_path")")
recipient=$(absolute_file "$(require_config_value XRAY_BACKUP_AGE_RECIPIENT_FILE "$config_path")")
ledger=$(absolute_file "$(require_config_value XRAY_SECURITY_LEDGER_SNAPSHOT_FILE "$config_path")")
backup_destination=$(require_config_value XRAY_RELEASE_BACKUP_DESTINATION "$config_path")
evidence_dir=$(require_config_value XRAY_RECOVERY_EVIDENCE_DIR "$config_path")

case "$backup_destination" in /*) ;; *) die "backup destination must be absolute" ;; esac
case "$evidence_dir" in /*) ;; *) die "recovery evidence directory must be absolute" ;; esac
[ -d "$backup_destination" ] || die "backup destination is unavailable"
[ -d "$evidence_dir" ] || die "recovery evidence directory is unavailable"

exec docker run --rm \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --user "$(id -u):$(id -g)" \
  --network "$network" \
  --tmpfs /tmp:rw,noexec,nosuid,size=512m \
  --mount "type=bind,src=$root_dir,dst=/workspace,readonly" \
  --mount "type=bind,src=$config_path,dst=$config_path,readonly" \
  --mount "type=bind,src=$pg_service,dst=$pg_service,readonly" \
  --mount "type=bind,src=$pgpass,dst=$pgpass,readonly" \
  --mount "type=bind,src=$recipient,dst=$recipient,readonly" \
  --mount "type=bind,src=$ledger,dst=$ledger,readonly" \
  --mount "type=bind,src=$backup_destination,dst=$backup_destination" \
  --mount "type=bind,src=$evidence_dir,dst=$evidence_dir" \
  --workdir /workspace \
  "$image" \
  "/workspace/deploy/backup/$action.sh" "$@" --config "$config_path"
