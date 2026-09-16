#!/usr/bin/env bash
set -euo pipefail

install_root=${XRAY_INSTALL_ROOT:-/usr/local}
config_dir=${XRAY_CONFIG_DIR:-/usr/local/etc/xray}
state_dir=${XRAY_STATE_DIR:-/var/lib/xray-manager}
xray_binary=${XRAY_BINARY:-$install_root/bin/xray}
manifest="$state_dir/installed-manifest.json"

fail() {
  jq -cn --arg code "$1" --arg message "$2" '{ok:false,error_code:$code,message:$message}'
  exit "$3"
}

command -v jq >/dev/null 2>&1 || fail TOOL_MISSING "jq is required" 10
[[ -x "$xray_binary" ]] || fail XRAY_BINARY_MISSING "xray binary is missing" 20
[[ -f "$manifest" ]] || fail MANIFEST_MISSING "installed manifest is missing" 20
expected_version=$(jq -r '.xray_version' "$manifest")
actual_version=$("$xray_binary" version 2>/dev/null | head -n 1)
[[ "$actual_version" == *"$expected_version"* ]] || fail VERSION_MISMATCH "xray version mismatch" 20
[[ -f "$state_dir/current-generation" ]] || fail STATE_MISSING "generation state is missing" 20
generation=$(<"$state_dir/current-generation")
[[ "$generation" =~ ^[0-9]+$ ]] || fail STATE_CORRUPT "generation state is invalid" 20
if [[ -f "$config_dir/config.json" ]]; then
  "$xray_binary" run -test -config "$config_dir/config.json" >/dev/null 2>&1 \
    || fail CONFIG_INVALID "installed config is invalid" 20
fi
jq -cn --arg version "$expected_version" --argjson generation "$generation" \
  '{ok:true,xray_version:$version,generation:$generation}'
