#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "$0")" >/dev/null 2>&1 && pwd)"
project_root="$(cd -- "$script_dir/../.." >/dev/null 2>&1 && pwd)"
compose_file="$script_dir/compose.yaml"
xray_binary="${XRAY_TEST_BINARY:-$project_root/runtime/xray/v26.3.27/xray}"
fixture_temp="$(mktemp -d)"
trap 'rm -rf -- "$fixture_temp"' EXIT

command -v docker >/dev/null 2>&1 || {
  echo "docker is required for fixed Clash/Mihomo parser validation" >&2
  exit 1
}
if [[ ! -x "$xray_binary" ]]; then
  echo "fixed Xray v26.3.27 binary is required: $xray_binary" >&2
  exit 1
fi
if ! bash "$project_root/scripts/check-xray-version.sh" "$xray_binary" >/dev/null; then
  echo "XRAY_TEST_BINARY is not the pinned Xray 26.3.27 runtime" >&2
  exit 1
fi

PYTHONPATH="$project_root/backend" "$project_root/backend/.venv/bin/python" \
  "$script_dir/generate_format_fixtures.py" "$fixture_temp"
python3 "$script_dir/verify_shadowrocket_fixture.py" \
  "$fixture_temp/shadowrocket.txt"
python3 "$script_dir/v2ray_to_xray.py" \
  "$fixture_temp/v2ray.txt" "$fixture_temp/xray-client.json"
"$xray_binary" run -test -config "$fixture_temp/xray-client.json"
SUBSCRIPTION_FIXTURE_DIR="$fixture_temp" \
  docker compose -f "$compose_file" run --rm --no-deps clash
SUBSCRIPTION_FIXTURE_DIR="$fixture_temp" \
  docker compose -f "$compose_file" run --rm --no-deps mihomo

echo "subscription format fixtures passed fixed parser validation"
