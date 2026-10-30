#!/usr/bin/env bash
set -euo pipefail
umask 077

# This wrapper keeps the existing offline installer as the single writer for
# Xray files. It only handles interaction, pinned download and update recovery.

install_root=${XRAY_INSTALL_ROOT:-/usr/local}
config_dir=${XRAY_CONFIG_DIR:-/usr/local/etc/xray}
state_dir=${XRAY_STATE_DIR:-/var/lib/xray-manager}
skip_systemd=${XRAY_SKIP_SYSTEMD:-0}
non_interactive=${XRAY_NONINTERACTIVE:-0}
action_override=${XRAY_ONE_CLICK_ACTION:-}
archive_override=${XRAY_ONE_CLICK_ARCHIVE:-}

source_path=${BASH_SOURCE[0]:-}
script_dir=
if [[ -n "$source_path" && -f "$source_path" ]]; then
  script_dir=$(cd -- "$(dirname -- "$source_path")" && pwd -P)
fi

repository=${XRAY_INSTALLER_REPOSITORY:-shiyi-log/X-ray}
ref=${XRAY_INSTALLER_REF:-v0.8.0}
raw_base=${XRAY_INSTALLER_RAW_BASE_URL:-https://raw.githubusercontent.com/${repository}/${ref}}

fail() {
  local code=$1
  local message=$2
  local exit_code=$3
  jq -cn --arg code "$code" --arg message "$message" \
    '{ok:false,error_code:$code,message:$message}'
  exit "$exit_code"
}

if (( EUID != 0 )) && [[ ${XRAY_ONE_CLICK_ALLOW_NONROOT:-0} != 1 ]]; then
  echo 'one-click installer must run as root (use sudo)' >&2
  exit 10
fi

[[ "$(uname -s)" == "Linux" ]] || {
  echo 'one-click installer supports Linux hosts only' >&2
  exit 10
}

if [[ "$skip_systemd" != "1" ]] && ! command -v systemctl >/dev/null 2>&1; then
  echo 'systemd is required; set XRAY_SKIP_SYSTEMD=1 only for an isolated test install' >&2
  exit 10
fi

install_missing_dependencies() {
  local missing=()
  command -v jq >/dev/null 2>&1 || missing+=(jq)
  command -v unzip >/dev/null 2>&1 || missing+=(unzip)
  command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1 || missing+=(curl)
  if ((${#missing[@]} == 0)); then
    return 0
  fi

  if ! command -v apt-get >/dev/null 2>&1; then
    echo "missing required commands: ${missing[*]}" >&2
    exit 10
  fi
  if [[ "$non_interactive" != "1" ]]; then
    printf '缺少依赖 %s，是否使用 apt-get 自动安装？[Y/n] ' "${missing[*]}"
    read -r answer
    case "$answer" in
      n|N|no|NO)
        echo 'required dependencies were not installed' >&2
        exit 10
        ;;
    esac
  fi
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl jq unzip
}

download_file() {
  local url=$1
  local destination=$2
  case "$url" in
    https://*) ;;
    *) fail DOWNLOAD_URL_INVALID "only HTTPS download URLs are accepted" 20 ;;
  esac
  if command -v curl >/dev/null 2>&1; then
    curl --fail --silent --show-error --location \
      --proto '=https' --proto-redir '=https' --tlsv1.2 \
      --connect-timeout 15 --max-time 300 --retry 2 \
      --output "$destination" "$url"
  else
    wget --https-only --secure-protocol=TLSv1_2 \
      --timeout=30 --tries=3 --quiet --output-document="$destination" "$url"
  fi
}

install_missing_dependencies

temporary_root=$(mktemp -d)
cleanup() {
  rm -rf "$temporary_root"
}
trap cleanup EXIT

helper_dir=$script_dir
manifest=${XRAY_MANIFEST:-}
if [[ -z "$helper_dir" || ! -f "$helper_dir/install.sh" || ! -f "$helper_dir/manifest.json" ]]; then
  case "$raw_base" in
    https://*) ;;
    *) fail INSTALLER_SOURCE_INVALID "remote installer source must use HTTPS" 20 ;;
  esac
  helper_dir="$temporary_root/helpers"
  mkdir -p "$helper_dir/licenses"
  for helper in install.sh verify.sh apply-config.sh inline-certificates.py xray.service manifest.json; do
    download_file "$raw_base/installer/$helper" "$helper_dir/$helper"
  done
  download_file "$raw_base/installer/licenses/MPL-2.0.txt" \
    "$helper_dir/licenses/MPL-2.0.txt"
  chmod 755 "$helper_dir"/*.sh "$helper_dir/inline-certificates.py"
  manifest="$helper_dir/manifest.json"
else
  manifest=${manifest:-$helper_dir/manifest.json}
fi

[[ -f "$manifest" ]] || fail MANIFEST_MISSING "installer manifest is missing" 10
command -v jq >/dev/null 2>&1 || fail TOOL_MISSING "jq is required" 10

machine=$(uname -m)
case "$machine" in
  x86_64|amd64) platform=linux-amd64 ;;
  arm64|aarch64) platform=linux-arm64 ;;
  *) fail ARCHITECTURE_UNSUPPORTED "unsupported Linux architecture" 10 ;;
esac

artifact=$(jq -ce --arg platform "$platform" '.artifacts[$platform] // empty' "$manifest") \
  || fail ARCHITECTURE_UNSUPPORTED "manifest has no artifact for this architecture" 10
expected_filename=$(jq -r '.filename' <<<"$artifact")
artifact_url=$(jq -r '.url' <<<"$artifact")
expected_hash=$(jq -r '.sha256' <<<"$artifact")
xray_version=$(jq -r '.xray_version' "$manifest")
[[ "$expected_filename" != *"/"* ]] || fail MANIFEST_INVALID "manifest filename is not a plain filename" 20
[[ "$artifact_url" == https://* ]] || fail MANIFEST_INVALID "manifest URL is not HTTPS" 20
[[ "$artifact_url" != *latest* ]] || fail MANIFEST_INVALID "manifest must not resolve latest" 20
[[ "$expected_hash" =~ ^[0-9a-fA-F]{64}$ ]] || fail MANIFEST_INVALID "manifest SHA-256 is invalid" 20

existing_install=0
if [[ -x "$install_root/bin/xray" || -f "$state_dir/installed-manifest.json" ]]; then
  existing_install=1
fi
default_action=install
((existing_install == 1)) && default_action=update

action=$action_override
if [[ -z "$action" ]]; then
  if [[ "$non_interactive" == "1" ]]; then
    action=$default_action
  else
    printf '选择操作：1) 全新安装  2) 更新已有安装 [%s]：' "$default_action"
    read -r selected
    case "$selected" in
      1) action=install ;;
      2) action=update ;;
      '') action=$default_action ;;
      *) fail INVALID_ACTION "choose install or update" 10 ;;
    esac
  fi
fi
case "$action" in
  install|update) ;;
  *) fail INVALID_ACTION "XRAY_ONE_CLICK_ACTION must be install or update" 10 ;;
esac

if [[ "$non_interactive" != "1" ]]; then
  printf '目标：%s，架构：%s，Xray：%s\n' "$action" "$platform" "$xray_version"
  printf '安装目录：%s；配置目录：%s；状态目录：%s\n' "$install_root" "$config_dir" "$state_dir"
  printf '继续？[y/N] '
  read -r confirmation
  case "$confirmation" in
    y|Y|yes|YES) ;;
    *) fail CANCELLED "installation cancelled" 10 ;;
  esac
fi

archive="$temporary_root/$expected_filename"
if [[ -n "$archive_override" ]]; then
  [[ -f "$archive_override" ]] || fail BUNDLE_MISSING "XRAY_ONE_CLICK_ARCHIVE does not exist" 10
  cp -- "$archive_override" "$archive"
else
  download_file "$artifact_url" "$archive"
fi

if command -v sha256sum >/dev/null 2>&1; then
  actual_hash=$(sha256sum "$archive" | awk '{print $1}')
else
  actual_hash=$(shasum -a 256 "$archive" | awk '{print $1}')
fi
[[ "$actual_hash" == "$expected_hash" ]] || fail BUNDLE_HASH_MISMATCH "Xray archive SHA-256 mismatch" 20

rollback_dir="$temporary_root/rollback"
mkdir -p "$rollback_dir"
old_binary_present=0
if [[ "$action" == "update" && -x "$install_root/bin/xray" ]]; then
  cp -p "$install_root/bin/xray" "$rollback_dir/xray"
  old_binary_present=1
  for data_file in geoip.dat geosite.dat; do
    if [[ -f "$install_root/share/xray/$data_file" ]]; then
      cp -p "$install_root/share/xray/$data_file" "$rollback_dir/$data_file"
    fi
  done
fi

restore_previous() {
  ((old_binary_present == 1)) || return 0
  install -m 755 "$rollback_dir/xray" "$install_root/bin/xray"
  for data_file in geoip.dat geosite.dat; do
    if [[ -f "$rollback_dir/$data_file" ]]; then
      install -m 644 "$rollback_dir/$data_file" "$install_root/share/xray/$data_file"
    fi
  done
}

set +e
install_output=$(env \
  "XRAY_MANIFEST=$manifest" \
  "XRAY_INSTALL_ROOT=$install_root" \
  "XRAY_CONFIG_DIR=$config_dir" \
  "XRAY_STATE_DIR=$state_dir" \
  "XRAY_SKIP_SYSTEMD=$skip_systemd" \
  "XRAY_PLATFORM=$platform" \
  bash "$helper_dir/install.sh" "$archive" 2>&1)
install_status=$?
set -e
printf '%s\n' "$install_output"
if ((install_status != 0)); then
  restore_previous
  fail INSTALL_FAILED "the pinned Xray installer failed" "$install_status"
fi

service_state=not-started-config-pending
if [[ "$skip_systemd" != "1" && -f "$config_dir/config.json" ]]; then
  if ! /bin/systemctl reset-failed xray >/dev/null 2>&1 || \
     ! /bin/systemctl restart xray >/dev/null 2>&1 || \
     ! /bin/systemctl is-active --quiet xray; then
    restore_previous
    /bin/systemctl reset-failed xray >/dev/null 2>&1 || true
    /bin/systemctl restart xray >/dev/null 2>&1 || true
    fail SERVICE_RESTART_FAILED "Xray service failed after install/update; previous binary restored when available" 40
  fi
  service_state=running
fi

set +e
verify_output=$(env \
  "XRAY_MANIFEST=$manifest" \
  "XRAY_INSTALL_ROOT=$install_root" \
  "XRAY_CONFIG_DIR=$config_dir" \
  "XRAY_STATE_DIR=$state_dir" \
  "XRAY_BINARY=$install_root/bin/xray" \
  bash "$helper_dir/verify.sh" 2>&1)
verify_status=$?
set -e
printf '%s\n' "$verify_output"
((verify_status == 0)) || fail VERIFY_FAILED "installed Xray verification failed" "$verify_status"

jq -cn \
  --arg action "$action" \
  --arg platform "$platform" \
  --arg xray_version "$xray_version" \
  --arg service_state "$service_state" \
  --argjson verified "$verify_output" \
  '{ok:true,action:$action,platform:$platform,xray_version:$xray_version,archive_verified:true,service_state:$service_state,verification:$verified}'
