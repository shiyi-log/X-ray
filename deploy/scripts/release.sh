#!/usr/bin/env sh
set -eu

script_dir=$(unset CDPATH; cd -- "$(dirname -- "$0")" && pwd -P)
root_dir=$(unset CDPATH; cd -- "$script_dir/../.." && pwd -P)
# shellcheck source=deploy/scripts/release-lib.sh
. "$script_dir/release-lib.sh"

usage() {
  echo "usage: release.sh --version <version> --digest <backend-sha256> --config <env-file> [--compose <file>]" >&2
  exit 2
}

version=
digest=
config_path=
compose_path="$root_dir/deploy/compose/production.yml"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --version) [ "$#" -ge 2 ] || usage; version=$2; shift 2 ;;
    --digest) [ "$#" -ge 2 ] || usage; digest=$2; shift 2 ;;
    --config) [ "$#" -ge 2 ] || usage; config_path=$2; shift 2 ;;
    --compose) [ "$#" -ge 2 ] || usage; compose_path=$2; shift 2 ;;
    *) usage ;;
  esac
done
if [ -z "$version" ] || [ -z "$digest" ] || [ -z "$config_path" ]; then
  usage
fi
printf '%s' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || die "invalid version"
printf '%s' "$digest" | grep -Eq '^sha256:[0-9a-f]{64}$' || die "invalid digest"
[ "$(tr -d '\r\n' <"$root_dir/VERSION")" = "$version" ] \
  || die "release version does not match VERSION"

XRAY_RELEASE_CONFIG=$(absolute_file "$config_path")
XRAY_RELEASE_COMPOSE=$(absolute_file "$compose_path")
export XRAY_RELEASE_CONFIG XRAY_RELEASE_COMPOSE
backend_image=$(require_config_value XRAY_BACKEND_IMAGE "$XRAY_RELEASE_CONFIG")
case "$backend_image" in *"@$digest") ;; *) die "backend image does not match --digest" ;; esac

"$script_dir/preflight.sh" --config "$XRAY_RELEASE_CONFIG" --compose "$XRAY_RELEASE_COMPOSE"
[ -x "$root_dir/deploy/backup/backup.sh" ] || die "backup workflow is unavailable"
backup_destination=$(require_config_value XRAY_RELEASE_BACKUP_DESTINATION "$XRAY_RELEASE_CONFIG")
"$root_dir/deploy/backup/backup.sh" --destination "$backup_destination" \
  --config "$XRAY_RELEASE_CONFIG"

compose --profile release run --rm database-bootstrap
compose --profile release run --rm migrator python /app/backend/manage.py migrate --plan --noinput
wait_for_worker_drain
compose --profile release run --rm migrator python /app/backend/manage.py migrate --noinput
compose --profile release run --rm database-bootstrap
compose --profile release run --rm migrator python /app/backend/manage.py migrate --check --noinput

compose up -d --wait admin-api subscription-api frontend gateway
compose up -d worker outbox-dispatcher
echo "released version=$version backend_digest=$digest"
