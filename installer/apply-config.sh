#!/usr/bin/env bash
set -euo pipefail
umask 077

state_dir=${XRAY_STATE_DIR:-/var/lib/xray-manager}
config_dir=${XRAY_CONFIG_DIR:-/usr/local/etc/xray}
xray_binary=${XRAY_BINARY:-/usr/local/bin/xray}
restart_binary=${XRAY_SERVICE_RESTART_BIN:-}

mkdir -p "$state_dir" "$config_dir"
request_file=$(mktemp "$state_dir/request.XXXXXX")
candidate_file=$(mktemp "$state_dir/candidate.XXXXXX")
lock_dir=""

cleanup() {
  rm -f "$request_file" "$candidate_file"
  if [[ -n "$lock_dir" ]]; then
    rmdir "$lock_dir" 2>/dev/null || true
  fi
}
trap cleanup EXIT

error_json() {
  local code=$1
  local message=$2
  local exit_code=$3
  jq -cn --arg code "$code" --arg message "$message" \
    '{ok:false,error_code:$code,message:$message,rollback_performed:false}'
  exit "$exit_code"
}

for required in jq "$xray_binary"; do
  if [[ "$required" == "jq" ]]; then
    command -v jq >/dev/null 2>&1 || error_json TOOL_MISSING "jq is required" 10
  elif [[ ! -x "$required" ]]; then
    error_json XRAY_BINARY_MISSING "xray binary is not executable" 10
  fi
done

IFS= read -r -d '' input_payload || true
printf '%s' "$input_payload" >"$request_file"
chmod 600 "$request_file"

if ! jq -e '
  .schema_version == 1 and
  (.node_id | type == "string" and test("^[0-9a-fA-F-]{36}$")) and
  (.generation | type == "number" and floor == . and . >= 1) and
  (.expected_previous_generation | type == "number" and floor == . and . >= 0) and
  (.config | type == "object") and
  (.action == "normal" or .action == "security")
' "$request_file" >/dev/null; then
  error_json INVALID_REQUEST "invalid apply request" 10
fi

generation=$(jq -r '.generation' "$request_file")
expected_previous=$(jq -r '.expected_previous_generation' "$request_file")
action=$(jq -r '.action' "$request_file")
jq -c '.config' "$request_file" >"$candidate_file"
chmod 600 "$candidate_file"

if command -v flock >/dev/null 2>&1; then
  exec 9>"$state_dir/apply.lock"
  flock -x 9
else
  lock_dir="$state_dir/apply.lock.d"
  if ! mkdir "$lock_dir" 2>/dev/null; then
    error_json APPLY_BUSY "another apply is in progress" 30
  fi
fi

generation_file="$state_dir/current-generation"
current_generation=0
if [[ -f "$generation_file" ]]; then
  current_generation=$(<"$generation_file")
  [[ "$current_generation" =~ ^[0-9]+$ ]] || error_json STATE_CORRUPT "invalid generation state" 30
fi
if (( generation <= current_generation || expected_previous != current_generation )); then
  error_json GENERATION_CONFLICT "configuration generation conflict" 30
fi

if ! "$xray_binary" run -test -config "$candidate_file" >/dev/null 2>&1; then
  error_json CONFIG_INVALID "xray rejected candidate configuration" 20
fi

hash_command=()
if command -v sha256sum >/dev/null 2>&1; then
  hash_command=(sha256sum)
else
  hash_command=(shasum -a 256)
fi
config_hash=$("${hash_command[@]}" "$candidate_file" | awk '{print $1}')
journal_tmp=$(mktemp "$state_dir/journal.XXXXXX")
jq -cn \
  --argjson generation "$generation" \
  --argjson previous "$current_generation" \
  --arg config_hash "$config_hash" \
  --arg phase PREPARED \
  '{generation:$generation,previous_generation:$previous,config_hash:$config_hash,phase:$phase}' \
  >"$journal_tmp"
chmod 600 "$journal_tmp"
mv -f "$journal_tmp" "$state_dir/apply-journal.json"

current_config="$config_dir/config.json"
backup_config="$state_dir/config.previous.json"
if [[ -f "$current_config" ]]; then
  install -m 600 "$current_config" "$backup_config"
else
  rm -f "$backup_config"
fi
install -m 600 "$candidate_file" "$config_dir/config.json.next"
mv -f "$config_dir/config.json.next" "$current_config"

generation_tmp=$(mktemp "$state_dir/generation.XXXXXX")
printf '%s\n' "$generation" >"$generation_tmp"
chmod 600 "$generation_tmp"
mv -f "$generation_tmp" "$generation_file"

jq '.phase = "CONFIG_INSTALLED"' "$state_dir/apply-journal.json" \
  >"$state_dir/apply-journal.json.next"
mv -f "$state_dir/apply-journal.json.next" "$state_dir/apply-journal.json"

restart_service() {
  if [[ -n "$restart_binary" ]]; then
    "$restart_binary"
  else
    /bin/systemctl restart xray
  fi
}

rollback_performed=false
if ! restart_service >/dev/null 2>&1; then
  if [[ "$action" == "normal" && -f "$backup_config" ]]; then
    install -m 600 "$backup_config" "$config_dir/config.json.rollback"
    mv -f "$config_dir/config.json.rollback" "$current_config"
    generation_tmp=$(mktemp "$state_dir/generation.XXXXXX")
    printf '%s\n' "$current_generation" >"$generation_tmp"
    chmod 600 "$generation_tmp"
    mv -f "$generation_tmp" "$generation_file"
    rollback_performed=true
    restart_service >/dev/null 2>&1 || true
  fi
  jq -cn \
    --argjson generation "$generation" \
    --argjson rollback_performed "$rollback_performed" \
    '{ok:false,error_code:"SERVICE_RESTART_FAILED",applied_generation:$generation,config_test_passed:true,service_restarted:false,rollback_performed:$rollback_performed}'
  exit 40
fi

jq '.phase = "COMMITTED"' "$state_dir/apply-journal.json" \
  >"$state_dir/apply-journal.json.next"
mv -f "$state_dir/apply-journal.json.next" "$state_dir/apply-journal.json"
jq -cn \
  --argjson generation "$generation" \
  --arg config_hash "$config_hash" \
  '{ok:true,applied_generation:$generation,config_test_passed:true,service_restarted:true,rollback_performed:false,config_hash:$config_hash}'
