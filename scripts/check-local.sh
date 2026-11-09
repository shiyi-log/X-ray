#!/usr/bin/env bash
set -euo pipefail

root_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd)
cd "$root_dir"

gate_names=(
  runtime
  compose-config
  django-check
  migration-drift
  ruff
  backend-tests
  openapi-determinism
  fixed-xray
  subscription-formats
  frontend-typecheck
  frontend-lint
  frontend-unit
  frontend-build
  frontend-e2e
  shellcheck
  boundary
  secrets
  skill
  acceptance-matrix
)

gate_descriptions=(
  "Python 3.13, Node >=22.18 and pnpm 10.33"
  "dedicated services, production/staging config and local image boundaries"
  "Django system check with test settings"
  "migration graph has no uncommitted model drift"
  "Ruff 0.13.1"
  "backend, installer, deployment, recovery and acceptance tests"
  "two identical OpenAPI generations and checked-in frontend types"
  "pinned Xray v26.3.27 asset and SHA-256 manifest"
  "four independent subscription format parsers"
  "frontend TypeScript"
  "frontend ESLint"
  "frontend unit tests"
  "frontend production build"
  "real browser login, resources, errors and revocation workflow"
  "ShellCheck v0.10.0"
  "Shop/archive isolation"
  "Gitleaks v8.24.3 fixed image fallback"
  "official X-ray project skill structure validation"
  "version-bound acceptance claims"
)

usage() {
  printf 'Usage: %s [--list]\n' "$0" >&2
}

if [[ ${1:-} == "--list" ]]; then
  for index in "${!gate_names[@]}"; do
    printf '%s\t%s\n' "${gate_names[$index]}" "${gate_descriptions[$index]}"
  done
  exit 0
fi
if [[ $# -ne 0 ]]; then
  usage
  exit 2
fi

version=$(<VERSION)
artifact_dir=${XRAY_ACCEPTANCE_ARTIFACT_DIR:-"$root_dir/artifacts/acceptance/$version/gates"}
mkdir -p "$artifact_dir"
summary_file="$artifact_dir/summary.tsv"
printf 'gate\texit_code\tstarted_at\tfinished_at\tlog\n' >"$summary_file"

export XRAY_TEST_DATABASE_URL=${XRAY_TEST_DATABASE_URL:-postgresql://xray_test:xray_test_only_password@127.0.0.1:${XRAY_TEST_POSTGRES_PORT:-55432}/xray_test}
export XRAY_REDIS_URL=${XRAY_REDIS_URL:-redis://127.0.0.1:${XRAY_TEST_REDIS_PORT:-56379}/0}
export XRAY_REQUIRE_FIXED_BINARY=1
export XRAY_ENV=test
export DJANGO_SETTINGS_MODULE=config.settings.test
export XRAY_TEST_BINARY=${XRAY_TEST_BINARY:-"$root_dir/runtime/xray/v26.3.27/xray"}
export XRAY_BACKEND_TEST_IMAGE=${XRAY_BACKEND_TEST_IMAGE:-"xray-manager-backend:$version-local"}
export XRAY_FRONTEND_TEST_IMAGE=${XRAY_FRONTEND_TEST_IMAGE:-"xray-manager-frontend:$version-local"}
export XRAY_BACKUP_TEST_IMAGE=${XRAY_BACKUP_TEST_IMAGE:-"xray-manager-backup-tools:$version-local"}

run_gate() {
  local gate=$1
  shift
  local log_file="$artifact_dir/$gate.log"
  local summary_log_path=$log_file
  local started_at finished_at exit_code gate_pid tee_pid tee_exit_code output_dir output_pipe
  if [[ $summary_log_path == "$root_dir/"* ]]; then
    summary_log_path=${summary_log_path#"$root_dir"/}
  fi
  started_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
  printf '\n[%s] %s\n' "$gate" "$started_at"
  set +e
  output_dir=$(mktemp -d "${TMPDIR:-/tmp}/xray-gate.XXXXXX")
  output_pipe="$output_dir/output"
  mkfifo "$output_pipe"
  tee "$log_file" <"$output_pipe" &
  tee_pid=$!
  (
    set -euo pipefail
    "$@"
  ) >"$output_pipe" 2>&1 &
  gate_pid=$!
  wait "$gate_pid"
  exit_code=$?
  wait "$tee_pid"
  tee_exit_code=$?
  if [[ $tee_exit_code -ne 0 ]]; then
    exit_code=$tee_exit_code
  fi
  unlink "$output_pipe"
  rmdir "$output_dir"
  set -e
  finished_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
  printf '%s\t%s\t%s\t%s\t%s\n' \
    "$gate" "$exit_code" "$started_at" "$finished_at" \
    "$summary_log_path" >>"$summary_file"
  if [[ $exit_code -ne 0 ]]; then
    printf 'gate failed: %s (exit %s)\n' "$gate" "$exit_code" >&2
    return "$exit_code"
  fi
}

ensure_image() {
  local image=$1
  local dockerfile=$2
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    docker build --file "$dockerfile" --tag "$image" "$root_dir"
  fi
}

ensure_fixed_xray() {
  if [[ ! -x "$XRAY_TEST_BINARY" ]]; then
    "$root_dir/scripts/fetch-xray-test-asset.sh"
  fi
  bash "$root_dir/scripts/check-xray-version.sh" "$XRAY_TEST_BINARY"
}

gate_compose_config() {
  if [[ ${XRAY_TEST_SERVICES_EXTERNAL:-0} != "1" ]]; then
    make compose-up
  fi
  make compose-config
  docker compose --env-file deploy/compose/config.example.env \
    -f deploy/compose/production.yml config --quiet
  docker compose --env-file deploy/compose/config.example.env \
    -f deploy/compose/staging.yml config --quiet

  ensure_image "$XRAY_BACKEND_TEST_IMAGE" deploy/docker/backend.Dockerfile
  ensure_image "$XRAY_FRONTEND_TEST_IMAGE" deploy/docker/frontend.Dockerfile
  ensure_image "$XRAY_BACKUP_TEST_IMAGE" deploy/docker/backup-tools.Dockerfile
}

gate_django_check() {
  uv run --project backend python backend/manage.py check --settings=config.settings.test
}

gate_migration_drift() {
  uv run --project backend python backend/manage.py makemigrations \
    --check --dry-run --settings=config.settings.test
}

gate_ruff() {
  uvx --from ruff==0.13.1 ruff check backend tests
}

gate_backend_tests() {
  ensure_fixed_xray
  docker image inspect "$XRAY_BACKEND_TEST_IMAGE" >/dev/null
  docker image inspect "$XRAY_FRONTEND_TEST_IMAGE" >/dev/null
  docker image inspect "$XRAY_BACKUP_TEST_IMAGE" >/dev/null
  uv run --project backend pytest -c backend/pyproject.toml backend/tests tests -q \
    --junitxml="$artifact_dir/backend-and-delivery.junit.xml"
}

gate_openapi() (
  set -euo pipefail
  local temporary
  temporary=$(mktemp -d)
  trap 'rm -rf -- "$temporary"' EXIT
  uv run --project backend python backend/manage.py spectacular \
    --file "$temporary/schema-one.yaml" --validate --settings=config.settings.test
  uv run --project backend python backend/manage.py spectacular \
    --file "$temporary/schema-two.yaml" --validate --settings=config.settings.test
  cmp "$temporary/schema-one.yaml" "$temporary/schema-two.yaml"
  cmp "$temporary/schema-one.yaml" backend/openapi/schema.yaml
  cp frontend/apps/web-antd/src/api/generated/schema.ts "$temporary/frontend-schema-before.ts"
  pnpm --dir frontend generate:api
  cmp "$temporary/frontend-schema-before.ts" \
    frontend/apps/web-antd/src/api/generated/schema.ts
)

gate_fixed_xray() {
  "$root_dir/scripts/fetch-xray-test-asset.sh"
  ensure_fixed_xray
}

gate_subscription_formats() {
  XRAY_TEST_BINARY="$XRAY_TEST_BINARY" tests/subscriptions/verify_formats.sh
}

gate_shellcheck() {
  local shellcheck_image
  local -a shell_files
  shellcheck_image='koalaman/shellcheck@sha256:2097951f02e735b613f4a34de20c40f937a6c8f18ecb170612c88c34517221fb'
  shell_files=()
  while IFS= read -r file; do
    shell_files+=("$file")
  done < <(git ls-files --cached --others --exclude-standard -- '*.sh')
  if [[ ${#shell_files[@]} -eq 0 ]]; then
    printf 'no tracked shell files found\n' >&2
    return 1
  fi
  if command -v shellcheck >/dev/null 2>&1 \
    && shellcheck --version | grep -Fq 'version: 0.10.0'; then
    shellcheck -x "${shell_files[@]}"
  elif command -v docker >/dev/null 2>&1; then
    docker run --rm \
      --mount "type=bind,src=$root_dir,dst=/repo,readonly" \
      --workdir /repo \
      "$shellcheck_image" -x "${shell_files[@]}"
  else
    printf 'ShellCheck v0.10.0 gate not run: local tool or Docker is required\n' >&2
    return 1
  fi
}

gate_skill() {
  local system_validator vendor_validator validator
  system_validator=${XRAY_SKILL_VALIDATOR:-/Users/a399/.codex/skills/.system/skill-creator/scripts/quick_validate.py}
  vendor_validator="$root_dir/scripts/vendor/skill-quick-validate.py"
  if [[ -f "$system_validator" ]]; then
    validator=$system_validator
  elif [[ -f "$vendor_validator" ]]; then
    validator=$vendor_validator
  else
    printf 'skill validator not run: official or vendored validator is required\n' >&2
    return 1
  fi
  "$root_dir/backend/.venv/bin/python" "$validator" skills/xray-manager
}

run_gate runtime "$root_dir/scripts/check-runtime.sh"
run_gate compose-config gate_compose_config
run_gate django-check gate_django_check
run_gate migration-drift gate_migration_drift
run_gate ruff gate_ruff
run_gate backend-tests gate_backend_tests
run_gate openapi-determinism gate_openapi
run_gate fixed-xray gate_fixed_xray
run_gate subscription-formats gate_subscription_formats
run_gate frontend-typecheck pnpm --dir frontend typecheck
run_gate frontend-lint pnpm --dir frontend lint
run_gate frontend-unit pnpm --dir frontend test:unit
run_gate frontend-build pnpm --dir frontend build
run_gate frontend-e2e pnpm --dir frontend test:e2e
run_gate shellcheck gate_shellcheck
run_gate boundary "$root_dir/scripts/check-boundary.sh"
run_gate secrets "$root_dir/scripts/check-secrets.sh"
run_gate skill gate_skill
run_gate acceptance-matrix python3 scripts/validate-acceptance.py

printf '\nall local acceptance gates passed; summary: %s\n' "$summary_file"
