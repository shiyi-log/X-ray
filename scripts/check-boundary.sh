#!/usr/bin/env bash
set -euo pipefail

root_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root_dir"

# This check only inspects backend Python and rejects imports of Shop roots.
if [[ -d backend ]]; then
  if rg -n --glob '*.py' '(^|[[:space:]])(from|import)[[:space:]]+(shop|orders|core|cloud)(\.|[[:space:]]|$)' backend; then
    echo 'boundary violation: backend imports a Shop implementation module' >&2
    exit 1
  fi
fi

# No build or test command may treat the local archive as an input directory.
if rg -n --hidden --glob '!archive/**' --glob '!.git/**' '/archive/|archive/shop-' Makefile scripts deploy backend frontend installer tests 2>/dev/null; then
  echo 'boundary violation: active project files reference archive/' >&2
  exit 1
fi

echo 'boundary check passed'
