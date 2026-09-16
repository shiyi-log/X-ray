#!/usr/bin/env bash
set -euo pipefail

root_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python_bin=${XRAY_PYTHON:-"$root_dir/backend/.venv/bin/python"}

[[ -x "$python_bin" ]] || { echo "missing Python runtime: $python_bin" >&2; exit 1; }
python_version=$($python_bin -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
case "$python_version" in
  3.13.*) ;;
  *)
    echo "Python 3.13 is required; found $python_version" >&2
    exit 1
    ;;
esac

node_bin=${XRAY_NODE:-node}
node_version=$($node_bin --version | sed 's/^v//')
node_major=${node_version%%.*}
node_minor=${node_version#*.}
node_minor=${node_minor%%.*}
if (( node_major < 22 || (node_major == 22 && node_minor < 18) )); then
  echo "Node.js >=22.18 is required; found $node_version" >&2
  exit 1
fi

pnpm_bin=${XRAY_PNPM:-pnpm}
pnpm_version=$($pnpm_bin --version)
[[ "$pnpm_version" == 10.33.* ]] || {
  echo "pnpm 10.33.x is required; found $pnpm_version" >&2
  exit 1
}

echo "runtime check passed: Python $python_version, Node $node_version, pnpm $pnpm_version"
