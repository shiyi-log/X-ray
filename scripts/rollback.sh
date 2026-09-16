#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'Usage: %s --to <tag-or-commit> [--apply]\n' "$0" >&2
  printf 'Without --apply this prints the safe revert plan only.\n' >&2
}

target=''
apply=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --to)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      target="$2"
      shift 2
      ;;
    --apply)
      apply=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

[[ -n "$target" ]] || { usage; exit 2; }
git rev-parse --verify "$target^{commit}" >/dev/null
if [[ -n "$(git status --porcelain)" ]]; then
  echo 'rollback refused: worktree is dirty; commit or stash changes first' >&2
  exit 1
fi

current=$(git rev-parse HEAD)
target_commit=$(git rev-parse "$target^{commit}")
if [[ "$current" == "$target_commit" ]]; then
  echo "already at $target ($target_commit)"
  exit 0
fi

echo "current: $current"
echo "target:  $target ($target_commit)"
echo 'database and external cloud state are not rolled back by this command.'
echo 'planned application revert:'
git log --oneline "$target_commit..HEAD"

if [[ "$apply" -eq 1 ]]; then
  git revert --no-edit "$target_commit..HEAD"
else
  echo "dry-run only; rerun with --apply to create explicit revert commits"
fi
