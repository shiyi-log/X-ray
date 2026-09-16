#!/usr/bin/env sh
set -eu
umask 077

script_dir=$(unset CDPATH; cd -- "$(dirname -- "$0")" && pwd -P)
root_dir=$(unset CDPATH; cd -- "$script_dir/../.." && pwd -P)
# shellcheck source=deploy/scripts/release-lib.sh
. "$root_dir/deploy/scripts/release-lib.sh"

usage() {
  echo "usage: verify.sh --backup <directory> --identity <age-key-file>" >&2
  exit 2
}

backup_dir=
identity=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --backup) [ "$#" -ge 2 ] || usage; backup_dir=$2; shift 2 ;;
    --identity) [ "$#" -ge 2 ] || usage; identity=$2; shift 2 ;;
    *) usage ;;
  esac
done
if [ -z "$backup_dir" ] || [ -z "$identity" ]; then usage; fi
case "$backup_dir" in /*) ;; *) die "backup path must be absolute" ;; esac
[ -d "$backup_dir" ] || die "backup directory is unavailable"
identity=$(absolute_file "$identity")
manifest=$(absolute_file "$backup_dir/manifest.json")
encrypted=$(absolute_file "$backup_dir/database.dump.age")

jq -e '
  .schema_version == 1 and
  .encrypted_dump == "database.dump.age" and
  (.encrypted_sha256 | test("^[0-9a-f]{64}$")) and
  (.plaintext_sha256 | test("^[0-9a-f]{64}$")) and
  (.security_ledger_sha256 | test("^[0-9a-f]{64}$")) and
  (.security_ledger_sequence | type == "number" and . >= 0) and
  (.control_key_version | type == "number" and . >= 1) and
  (.subscription_key_version | type == "number" and . >= 1)
' "$manifest" >/dev/null || die "backup manifest is invalid"

expected_encrypted=$(jq -er '.encrypted_sha256' "$manifest")
[ "$(sha256_file "$encrypted")" = "$expected_encrypted" ] \
  || die "encrypted backup checksum mismatch"

temp_dir=$(mktemp -d "${TMPDIR:-/tmp}/xray-verify.XXXXXX")
cleanup() { rm -rf -- "$temp_dir"; }
trap cleanup EXIT HUP INT TERM
age --decrypt -i "$identity" -o "$temp_dir/database.dump" "$encrypted"
expected_plaintext=$(jq -er '.plaintext_sha256' "$manifest")
[ "$(sha256_file "$temp_dir/database.dump")" = "$expected_plaintext" ] \
  || die "decrypted backup checksum mismatch"
pg_restore --list "$temp_dir/database.dump" >/dev/null
echo "backup verification passed"
