#!/usr/bin/env bash
set -euo pipefail

root_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root_dir"

# Scan tracked files only; local .env files and archive/ are ignored by design.
if ! command -v gitleaks >/dev/null 2>&1; then
  echo 'gitleaks is not installed; running conservative tracked-file checks' >&2
  files=$(git ls-files ':!:archive/**' ':!*.lock' ':!scripts/check-secrets.sh' || true)
  if [[ -n "$files" ]] && rg -n -e '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' -e 'AKIA[0-9A-Z]{16}' -e 'xoxb-' $files; then
    echo 'possible secret found in tracked files' >&2
    exit 1
  fi
else
  gitleaks detect --no-banner --redact --source . --log-opts='--all' --config=.gitleaks.toml
fi

echo 'secret scan passed'
