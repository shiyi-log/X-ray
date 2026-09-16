#!/usr/bin/env bash
set -euo pipefail
umask 077

root_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
manifest="$root_dir/installer/manifest.json"
runtime_dir="$root_dir/runtime/xray/v26.3.27"

command -v jq >/dev/null 2>&1 || { echo 'jq is required' >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo 'curl is required' >&2; exit 1; }
command -v unzip >/dev/null 2>&1 || { echo 'unzip is required' >&2; exit 1; }

os_name=$(uname -s | tr '[:upper:]' '[:lower:]')
case "$(uname -m)" in
  x86_64|amd64) architecture=amd64 ;;
  arm64|aarch64) architecture=arm64 ;;
  *) echo 'unsupported test architecture' >&2; exit 1 ;;
esac
platform="$os_name-$architecture"
artifact=$(jq -ce --arg platform "$platform" '.artifacts[$platform] // empty' "$manifest") \
  || { echo "no pinned test artifact for $platform" >&2; exit 1; }
filename=$(jq -r '.filename' <<<"$artifact")
url=$(jq -r '.url' <<<"$artifact")
expected=$(jq -r '.sha256' <<<"$artifact")

mkdir -p "$runtime_dir"
archive="$runtime_dir/$filename"
if [[ ! -f "$archive" ]]; then
  partial="$archive.partial"
  rm -f "$partial"
  curl --fail --location --proto '=https' --tlsv1.2 --output "$partial" "$url"
  mv -f "$partial" "$archive"
fi
if command -v sha256sum >/dev/null 2>&1; then
  actual=$(sha256sum "$archive" | awk '{print $1}')
else
  actual=$(shasum -a 256 "$archive" | awk '{print $1}')
fi
[[ "$actual" == "$expected" ]] || { echo 'pinned Xray test asset hash mismatch' >&2; exit 1; }

unzip -oq "$archive" xray -d "$runtime_dir"
chmod 755 "$runtime_dir/xray"
"$runtime_dir/xray" version | head -n 1
printf '%s\n' "$runtime_dir/xray"
