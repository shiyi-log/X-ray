#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
manifest=${XRAY_MANIFEST:-$script_dir/manifest.json}
archive=${1:-}
install_root=${XRAY_INSTALL_ROOT:-/usr/local}
config_dir=${XRAY_CONFIG_DIR:-/usr/local/etc/xray}
state_dir=${XRAY_STATE_DIR:-/var/lib/xray-manager}
skip_systemd=${XRAY_SKIP_SYSTEMD:-0}

fail() {
  jq -cn --arg code "$1" --arg message "$2" '{ok:false,error_code:$code,message:$message}'
  exit "$3"
}

command -v jq >/dev/null 2>&1 || fail TOOL_MISSING "jq is required" 10
command -v unzip >/dev/null 2>&1 || fail TOOL_MISSING "unzip is required" 10
[[ -f "$manifest" ]] || fail MANIFEST_MISSING "manifest is missing" 10
[[ -n "$archive" && -f "$archive" ]] || fail BUNDLE_MISSING "offline bundle is required" 10

os_name=$(uname -s | tr '[:upper:]' '[:lower:]')
machine=$(uname -m)
case "$machine" in
  x86_64|amd64) architecture=amd64 ;;
  arm64|aarch64) architecture=arm64 ;;
  *) fail ARCHITECTURE_UNSUPPORTED "unsupported architecture" 10 ;;
esac
platform=${XRAY_PLATFORM:-$os_name-$architecture}
artifact=$(jq -ce --arg platform "$platform" '.artifacts[$platform] // empty' "$manifest") \
  || fail ARCHITECTURE_UNSUPPORTED "manifest has no artifact for platform" 10
expected_filename=$(jq -r '.filename' <<<"$artifact")
expected_hash=$(jq -r '.sha256' <<<"$artifact")
xray_version=$(jq -r '.xray_version' "$manifest")
[[ "$(basename "$archive")" == "$expected_filename" ]] \
  || fail BUNDLE_NAME_MISMATCH "bundle filename does not match manifest" 10

if command -v sha256sum >/dev/null 2>&1; then
  actual_hash=$(sha256sum "$archive" | awk '{print $1}')
else
  actual_hash=$(shasum -a 256 "$archive" | awk '{print $1}')
fi
[[ "$actual_hash" == "$expected_hash" ]] || fail BUNDLE_HASH_MISMATCH "bundle hash mismatch" 20

extract_dir=$(mktemp -d)
trap 'rm -rf "$extract_dir"' EXIT
unzip -q "$archive" -d "$extract_dir"
[[ -x "$extract_dir/xray" ]] || fail BUNDLE_INVALID "xray executable is missing" 20
version_output=$("$extract_dir/xray" version 2>/dev/null | head -n 1)
[[ "$version_output" == *"$xray_version"* ]] || fail VERSION_MISMATCH "xray version mismatch" 20

mkdir -p "$install_root/bin" "$install_root/share/xray" "$config_dir" "$state_dir"
install -m 755 "$extract_dir/xray" "$install_root/bin/xray"
for data_file in geoip.dat geosite.dat; do
  [[ -f "$extract_dir/$data_file" ]] || fail BUNDLE_INVALID "$data_file is missing" 20
  install -m 644 "$extract_dir/$data_file" "$install_root/share/xray/$data_file"
done
install -m 644 "$manifest" "$state_dir/installed-manifest.json"
install -m 644 "$script_dir/licenses/MPL-2.0.txt" "$state_dir/XRAY-LICENSE.txt"
printf '0\n' >"$state_dir/current-generation"
chmod 600 "$state_dir/current-generation"

if [[ "$skip_systemd" != "1" && "$os_name" == "linux" ]]; then
  install -m 644 "$script_dir/xray.service" /etc/systemd/system/xray.service
  /bin/systemctl daemon-reload
  /bin/systemctl enable xray.service >/dev/null
fi

jq -cn --arg version "$xray_version" --arg platform "$platform" \
  '{ok:true,xray_version:$version,platform:$platform,verified:true}'
