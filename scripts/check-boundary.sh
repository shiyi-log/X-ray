#!/usr/bin/env bash
set -euo pipefail

root_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root_dir"

if command -v rg >/dev/null 2>&1; then
  scan_backend_imports() {
    local exit_code
    set +e
    rg -n \
      --glob '*.py' \
      --glob '!**/.venv/**' \
      --glob '!**/__pycache__/**' \
      --glob '!**/.pytest_cache/**' \
      --glob '!**/.mypy_cache/**' \
      '(^|[[:space:]])(from|import)[[:space:]]+(shop|orders|core|cloud)(\.|[[:space:]]|$)' \
      backend
    exit_code=$?
    set -e
    return "$exit_code"
  }

  scan_archive_references() {
    local exit_code
    set +e
    rg -n --hidden \
      --glob '!archive/**' \
      --glob '!.git/**' \
      --glob '!**/.venv/**' \
      --glob '!**/__pycache__/**' \
      --glob '!**/.pytest_cache/**' \
      --glob '!**/.mypy_cache/**' \
      --glob '!**/node_modules/**' \
      --glob '!**/dist/**' \
      --glob '!**/build/**' \
      --glob '!scripts/check-boundary.sh' \
      '/archive/|archive/shop-' \
      "${scan_roots[@]}"
    exit_code=$?
    set -e
    return "$exit_code"
  }
elif command -v find >/dev/null 2>&1 && command -v grep >/dev/null 2>&1; then
  scan_file_list() {
    local pattern=$1
    local file_list=$2
    local matched=1
    local exit_code

    while IFS= read -r -d '' file; do
      set +e
      grep -nE "$pattern" "$file"
      exit_code=$?
      set -e
      case "$exit_code" in
        0) matched=0 ;;
        1) ;;
        *)
          printf 'boundary scan failed while reading %s (grep exit %s)\n' \
            "$file" "$exit_code" >&2
          return "$exit_code"
          ;;
      esac
    done <"$file_list"

    return "$matched"
  }

  scan_backend_imports() {
    local file_list
    local find_exit
    file_list=$(mktemp "${TMPDIR:-/tmp}/xray-boundary.XXXXXX") || {
      echo 'boundary scan failed: unable to create a temporary file' >&2
      return 2
    }
    if find backend \
      -type d \( -name .venv -o -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache \) -prune -o \
      -type f -name '*.py' -print0 >"$file_list"; then
      find_exit=0
    else
      find_exit=$?
    fi
    if [[ "$find_exit" -ne 0 ]]; then
      rm -f -- "$file_list"
      printf 'boundary scan failed while enumerating backend files (find exit %s)\n' \
        "$find_exit" >&2
      return "$find_exit"
    fi

    set +e
    scan_file_list \
      '(^|[[:space:]])(from|import)[[:space:]]+(shop|orders|core|cloud)(\.|[[:space:]]|$)' \
      "$file_list"
    local scan_exit=$?
    set -e
    rm -f -- "$file_list"
    return "$scan_exit"
  }

  scan_archive_references() {
    local file_list
    local find_exit
    file_list=$(mktemp "${TMPDIR:-/tmp}/xray-boundary.XXXXXX") || {
      echo 'boundary scan failed: unable to create a temporary file' >&2
      return 2
    }
    if find "${scan_roots[@]}" \
      -type d \( -name .git -o -name archive -o -name .venv -o -name __pycache__ \
        -o -name .pytest_cache -o -name .mypy_cache -o -name node_modules \
        -o -name dist -o -name build \) -prune -o \
      -type f ! -path "$root_dir/scripts/check-boundary.sh" \
      ! -path 'scripts/check-boundary.sh' -print0 >"$file_list"; then
      find_exit=0
    else
      find_exit=$?
    fi
    if [[ "$find_exit" -ne 0 ]]; then
      rm -f -- "$file_list"
      printf 'boundary scan failed while enumerating project files (find exit %s)\n' \
        "$find_exit" >&2
      return "$find_exit"
    fi

    set +e
    scan_file_list '/archive/|archive/shop-' "$file_list"
    local scan_exit=$?
    set -e
    rm -f -- "$file_list"
    return "$scan_exit"
  }
else
  echo 'boundary check unavailable: rg, find and grep are required' >&2
  exit 2
fi

# This check only inspects backend Python and rejects imports of Shop roots.
if [[ -d backend ]]; then
  if scan_backend_imports; then
    echo 'boundary violation: backend imports a Shop implementation module' >&2
    exit 1
  else
    scan_exit=$?
    if [[ "$scan_exit" -ne 1 ]]; then
      printf 'boundary check failed: backend scan exited %s\n' "$scan_exit" >&2
      exit "$scan_exit"
    fi
  fi
fi

# No build or test command may treat the local archive as an input directory.
scan_roots=(Makefile scripts deploy backend installer tests)
[[ ! -d frontend ]] || scan_roots+=(frontend)
if scan_archive_references; then
  echo 'boundary violation: active project files reference archive/' >&2
  exit 1
else
  scan_exit=$?
  if [[ "$scan_exit" -ne 1 ]]; then
    printf 'boundary check failed: archive scan exited %s\n' "$scan_exit" >&2
    exit "$scan_exit"
  fi
fi

echo 'boundary check passed'
