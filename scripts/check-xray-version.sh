#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! -x $1 ]]; then
  echo 'an executable Xray binary is required' >&2
  exit 2
fi

version_output=$("$1" version)
first_line=${version_output%%$'\n'*}
if [[ $first_line != *'Xray 26.3.27'* ]]; then
  echo 'Xray test binary must be version 26.3.27' >&2
  exit 1
fi

printf '%s\n' "$first_line"
