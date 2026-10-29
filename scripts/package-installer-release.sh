#!/usr/bin/env bash
set -euo pipefail
umask 077

root_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$root_dir"

version=${1:-$(<VERSION)}
expected_version=$(<VERSION)
[[ "$version" == "$expected_version" ]] || {
  printf 'release version %s does not match VERSION %s\n' "$version" "$expected_version" >&2
  exit 2
}

tag=${XRAY_RELEASE_TAG:-v${version}}
[[ "$tag" == "v${version}" ]] || {
  printf 'release tag %s does not match v%s\n' "$tag" "$version" >&2
  exit 2
}

dist_dir=${XRAY_RELEASE_DIST_DIR:-$root_dir/dist}
archive="$dist_dir/xray-installer-${version}.tar.gz"
release_manifest="$dist_dir/xray-installer-${version}-manifest.json"
checksums="$dist_dir/SHA256SUMS"
stage_parent=$(mktemp -d)
stage_dir="$stage_parent/xray-installer-${version}"
trap 'rm -rf -- "$stage_parent"' EXIT

mkdir -p "$dist_dir" "$stage_dir"
cp -R installer "$stage_dir/installer"
cp VERSION CHANGELOG.md "$stage_dir/"

commit=$(git rev-parse HEAD)
python3 - "$stage_dir/release-manifest.json" "$version" "$tag" "$commit" <<'PY'
import json
import sys
from pathlib import Path

target, version, tag, commit = sys.argv[1:]
root = Path(target).parent.parent
files = sorted(
    str(path.relative_to(root))
    for path in root.joinpath(Path(target).parent.name, "installer").rglob("*")
    if path.is_file()
)
Path(target).write_text(
    json.dumps(
        {"version": version, "tag": tag, "commit": commit, "files": files},
        ensure_ascii=True,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY

rm -f "$archive" "$release_manifest" "$checksums"
tar -czf "$archive" -C "$stage_parent" "$(basename "$stage_dir")"
cp "$stage_dir/release-manifest.json" "$release_manifest"

hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

{
  printf '%s  %s\n' "$(hash_file "$archive")" "$(basename "$archive")"
  printf '%s  %s\n' "$(hash_file "$release_manifest")" "$(basename "$release_manifest")"
} >"$checksums"

printf 'created %s\ncreated %s\ncreated %s\n' "$archive" "$release_manifest" "$checksums"
