#!/usr/bin/env sh

# Shared, side-effect-free helpers for release scripts. This file is sourced.

die() {
  echo "$*" >&2
  exit 1
}

absolute_file() {
  candidate=$1
  [ -f "$candidate" ] || die "file is unavailable: $candidate"
  candidate_dir=$(unset CDPATH; cd -- "$(dirname -- "$candidate")" && pwd -P)
  printf '%s/%s\n' "$candidate_dir" "$(basename -- "$candidate")"
}

config_value() {
  key=$1
  config=$2
  awk -v wanted="$key" '
    /^[[:space:]]*(#|$)/ { next }
    index($0, wanted "=") == 1 {
      value = substr($0, length(wanted) + 2)
      sub(/\r$/, "", value)
      print value
      found = 1
      exit
    }
    END { if (!found) exit 1 }
  ' "$config"
}

require_config_value() {
  key=$1
  config=$2
  value=$(config_value "$key" "$config") || die "missing configuration: $key"
  [ -n "$value" ] || die "empty configuration: $key"
  printf '%s\n' "$value"
}

compose() {
  docker compose --env-file "$XRAY_RELEASE_CONFIG" -f "$XRAY_RELEASE_COMPOSE" "$@"
}

sha256_file() {
  target=$1
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$target" | awk '{print $1}'
  else
    shasum -a 256 "$target" | awk '{print $1}'
  fi
}

file_mode() {
  target=$1
  if stat -f '%Lp' "$target" >/dev/null 2>&1; then
    stat -f '%Lp' "$target"
  else
    stat -c '%a' "$target"
  fi
}

wait_for_worker_drain() {
  timeout_seconds=${XRAY_WORKER_DRAIN_SECONDS:-300}
  case "$timeout_seconds" in
    ''|*[!0-9]*) die "XRAY_WORKER_DRAIN_SECONDS must be an integer" ;;
  esac

  if ! compose ps --status running --services | grep -qx worker; then
    return 0
  fi

  compose exec -T worker celery -A config.celery:app control cancel_consumer celery \
    >/dev/null
  started_at=$(date +%s)
  while :; do
    active_json=$(compose exec -T worker celery -A config.celery:app inspect active \
      --json 2>/dev/null || true)
    if printf '%s' "$active_json" | python3 -c '
import json, sys
try:
    document = json.load(sys.stdin)
except (ValueError, TypeError):
    raise SystemExit(1)
raise SystemExit(0 if document and all(not tasks for tasks in document.values()) else 1)
'; then
      compose stop -t 60 worker outbox-dispatcher security-ledger-dispatcher
      return 0
    fi
    now=$(date +%s)
    if [ $((now - started_at)) -ge "$timeout_seconds" ]; then
      die "worker drain timed out; consumer remains paused and release was not switched"
    fi
    sleep 2
  done
}
