#!/usr/bin/env sh
set -eu

script_dir=$(unset CDPATH; cd -- "$(dirname -- "$0")" && pwd -P)
root_dir=$(unset CDPATH; cd -- "$script_dir/../.." && pwd -P)
# shellcheck source=deploy/scripts/release-lib.sh
. "$script_dir/release-lib.sh"

usage() {
  echo "usage: rollback.sh --version <previous> --config <env-file> [--compose <file>]" >&2
  exit 2
}

previous=
config_path=
compose_path="$root_dir/deploy/compose/production.yml"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --version) [ "$#" -ge 2 ] || usage; previous=$2; shift 2 ;;
    --config) [ "$#" -ge 2 ] || usage; config_path=$2; shift 2 ;;
    --compose) [ "$#" -ge 2 ] || usage; compose_path=$2; shift 2 ;;
    *) usage ;;
  esac
done
if [ -z "$previous" ] || [ -z "$config_path" ]; then
  usage
fi
printf '%s' "$previous" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || die "invalid version"

XRAY_RELEASE_CONFIG=$(absolute_file "$config_path")
XRAY_RELEASE_COMPOSE=$(absolute_file "$compose_path")
export XRAY_RELEASE_CONFIG XRAY_RELEASE_COMPOSE
"$script_dir/preflight.sh" --config "$XRAY_RELEASE_CONFIG" --compose "$XRAY_RELEASE_COMPOSE"

# REVOCATION records, token tombstones, credentials, and cloud outcomes are
# forward-only security state. Rollback changes images only and never restores DB data.
wait_for_worker_drain
compose up -d --wait --no-deps admin-api subscription-api frontend gateway
compose up -d --no-deps worker outbox-dispatcher security-ledger-dispatcher
echo "application images rolled back to configured version=$previous; database unchanged"
