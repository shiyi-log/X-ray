#!/usr/bin/env bash
set -euo pipefail

root_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd)
cd "$root_dir"

# Keep the fallback scanner identical across hosts. The digest is the v8.24.3
# multi-architecture index, not a mutable tag.
gitleaks_image='ghcr.io/gitleaks/gitleaks@sha256:e1b35e12a8c6fa8901f060459cfb6b2fc4c484d3afbe3b029733a3bbfab07055'

if command -v gitleaks >/dev/null 2>&1 \
  && gitleaks version 2>/dev/null | grep -Fq '8.24.3'; then
  gitleaks detect --no-banner --redact --source . --log-opts='--all' --config=.gitleaks.toml
elif command -v docker >/dev/null 2>&1; then
  docker run --rm \
    --mount "type=bind,src=$root_dir,dst=/repo,readonly" \
    --workdir /repo \
    "$gitleaks_image" \
    detect --no-banner --redact --source /repo --log-opts='--all' \
    --config=/repo/.gitleaks.toml
else
  echo 'secret scan not run: Gitleaks v8.24.3 or Docker is required' >&2
  exit 1
fi

echo 'secret scan passed'
