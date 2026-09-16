#!/usr/bin/env sh
set -eu

usage() {
  echo "usage: retention.sh --destination <directory> [--apply]" >&2
  exit 2
}

destination=
apply=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --destination) [ "$#" -ge 2 ] || usage; destination=$2; shift 2 ;;
    --apply) apply=1; shift ;;
    *) usage ;;
  esac
done
[ -n "$destination" ] || usage
case "$destination" in /*) ;; *) echo "destination must be absolute" >&2; exit 1 ;; esac
case "$destination" in /|/var|/var/lib) echo "destination is too broad" >&2; exit 1 ;; esac
[ -d "$destination" ] || { echo "destination is unavailable" >&2; exit 1; }

trash="$destination/.trash"
index=0
find "$destination" -mindepth 1 -maxdepth 1 -type d -name 'xray-*' \
  -print | sort -r | while IFS= read -r backup; do
    index=$((index + 1))
    if [ "$index" -le 35 ]; then
      continue
    fi
    if [ "$apply" -eq 1 ]; then
      mkdir -p "$trash"
      chmod 0700 "$trash"
      mv "$backup" "$trash/$(basename "$backup")"
      echo "moved to retention trash: $backup"
    else
      echo "would move to retention trash: $backup"
    fi
  done
