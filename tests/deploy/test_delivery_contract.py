from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_compose_isolates_data_services_and_subscription_secrets(environment):
    document = yaml.safe_load(
        (ROOT / f"deploy/compose/{environment}.yml").read_text(encoding="utf-8")
    )
    services = document["services"]
    assert {
        "postgres",
        "redis",
        "admin-api",
        "subscription-api",
        "worker",
        "outbox-dispatcher",
        "frontend",
        "gateway",
    }.issubset(services)
    assert "ports" not in services["postgres"]
    assert "ports" not in services["redis"]
    assert "ports" not in services["admin-api"]
    assert "ports" not in services["subscription-api"]
    subscription_secrets = set(services["subscription-api"].get("secrets", []))
    assert subscription_secrets == {
        "subscription_master_key",
        "subscription_db_password",
    }
    assert "control_master_key" not in subscription_secrets
    assert "cloud_credentials" not in subscription_secrets
    assert "control_master_key" in services["admin-api"]["secrets"]
    assert "cloud_credentials" in services["worker"]["secrets"]
    assert services["subscription-api"]["read_only"] is True
    assert services["worker"]["read_only"] is True
    assert services["gateway"]["read_only"] is True
    for service in services.values():
        assert service.get("privileged") is not True
        assert service.get("network_mode") != "host"


def test_public_nginx_surface_is_token_only_and_default_denies():
    subscription = (ROOT / "deploy/nginx/subscription.conf").read_text(encoding="utf-8")
    default_deny = (ROOT / "deploy/nginx/default-deny.conf").read_text(encoding="utf-8")
    admin = (ROOT / "deploy/nginx/admin.conf").read_text(encoding="utf-8")
    assert "[A-Za-z0-9_-]{43}" in subscription
    assert "limit_except GET HEAD" in subscription
    assert "access_log off" in subscription
    assert "proxy_no_cache 1" in subscription
    assert "location / { return 404; }" in subscription
    assert "default_server" in default_deny
    assert "return 404" in default_deny
    assert "/api/v1/" in admin
    assert "allow " in admin and "deny all" in admin


@pytest.mark.parametrize(
    "dockerfile", ["deploy/docker/backend.Dockerfile", "deploy/docker/frontend.Dockerfile"]
)
def test_runtime_images_are_non_root_and_copy_only_allowlisted_paths(dockerfile):
    content = (ROOT / dockerfile).read_text(encoding="utf-8")
    assert "USER 10001" in content
    assert "COPY . " not in content
    assert "archive" not in content.lower()
    assert "HEALTHCHECK" in content


def test_release_and_rollback_never_restore_database_state():
    release = (ROOT / "deploy/scripts/release.sh").read_text(encoding="utf-8")
    rollback = (ROOT / "deploy/scripts/rollback.sh").read_text(encoding="utf-8")
    preflight = (ROOT / "deploy/scripts/preflight.sh").read_text(encoding="utf-8")
    assert "migrate --plan" in release
    assert "run-in-tools.sh" in release
    assert ' backup \\' in release
    assert "migrate --check" in release
    assert "pg_restore" not in rollback
    assert "restore.sh" not in rollback
    assert "REVOCATION" in rollback
    assert "--config" in preflight


def test_docker_context_excludes_reference_data_and_secret_material():
    content = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    required = {"archive/", ".git/", ".env", "**/secrets/", "backups/", "runtime/"}
    assert required.issubset(set(content.splitlines()))


def test_local_gate_lists_complete_order_without_real_cloud_actions():
    result = subprocess.run(
        [str(ROOT / "scripts/check-local.sh"), "--list"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    gates = result.stdout.splitlines()
    expected = [
        "runtime",
        "compose-config",
        "django-check",
        "migration-drift",
        "ruff",
        "backend-tests",
        "openapi-determinism",
        "fixed-xray",
        "subscription-formats",
        "frontend-typecheck",
        "frontend-lint",
        "frontend-unit",
        "frontend-build",
        "frontend-e2e",
        "shellcheck",
        "boundary",
        "secrets",
        "skill",
        "acceptance-matrix",
    ]
    assert [line.split("\t", 1)[0] for line in gates] == expected
    lowered = result.stdout.lower()
    for forbidden in (
        "aws_access_key",
        "aliyun_access_key",
        "create_instances",
        "delete_instance",
        "release_ip",
        "google.com",
    ):
        assert forbidden not in lowered


def test_local_gate_summary_uses_the_selected_artifact_directory():
    script = (ROOT / "scripts/check-local.sh").read_text(encoding="utf-8")

    assert "local summary_log_path=$log_file" in script
    assert '"$summary_log_path" >>"$summary_file"' in script
    assert '"artifacts/acceptance/$version/gates/$gate.log"' not in script


def test_local_gate_stops_after_a_failed_command_inside_a_gate(tmp_path):
    script = (ROOT / "scripts/check-local.sh").read_text(encoding="utf-8")
    match = re.search(
        r"(?ms)^run_gate\(\) \{\n.*?^\}\n(?=\nensure_image\(\))", script
    )
    assert match is not None
    shell = f"""
set -uo pipefail
root_dir={str(ROOT)!r}
artifact_dir=$TEST_ARTIFACT_DIR
summary_file=$TEST_SUMMARY_FILE
printf 'gate\\texit_code\\tstarted_at\\tfinished_at\\tlog\\n' >"$summary_file"
{match.group(0)}
failing_gate() {{
  printf 'gate-before-failure\\n'
  false
  printf 'gate-after-failure\\n'
}}
run_gate failing_gate failing_gate
"""
    environment = {
        **os.environ,
        "TEST_ARTIFACT_DIR": str(tmp_path),
        "TEST_SUMMARY_FILE": str(tmp_path / "summary.tsv"),
    }
    result = subprocess.run(
        ["bash", "-c", shell],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1, result.stderr
    assert "gate failed: failing_gate (exit 1)" in result.stderr
    log = (tmp_path / "failing_gate.log").read_text(encoding="utf-8")
    assert "gate-before-failure" in log
    assert "gate-after-failure" not in log
    assert (tmp_path / "summary.tsv").read_text(encoding="utf-8").splitlines()[1].split(
        "\t"
    )[1] == "1"


def test_fixed_xray_version_check_consumes_complete_version_output(tmp_path):
    script = (ROOT / "scripts/check-local.sh").read_text(encoding="utf-8")
    match = re.search(r"(?ms)^ensure_fixed_xray\(\) \{\n.*?^\}", script)
    assert match is not None

    fake_binary = tmp_path / "xray"
    fake_binary.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "sys.stdout.write('Xray 26.3.27 fixture\\n')\n"
        "sys.stdout.write('x' * 1000000 + '\\n')\n",
        encoding="utf-8",
    )
    fake_binary.chmod(0o755)
    shell = f"""
set -euo pipefail
root_dir={str(ROOT)!r}
XRAY_TEST_BINARY={str(fake_binary)!r}
{match.group(0)}
ensure_fixed_xray
"""

    result = subprocess.run(
        ["bash", "-c", shell], cwd=ROOT, text=True, capture_output=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert "Xray 26.3.27 fixture" in result.stdout


def test_test_stack_honors_project_registered_database_ports():
    environment = {
        **os.environ,
        "XRAY_TEST_POSTGRES_PORT": "55435",
        "XRAY_TEST_REDIS_PORT": "56382",
        "XRAY_TEST_POSTGRES_VOLUME": "xray-gate-test-postgres",
        "XRAY_TEST_REDIS_VOLUME": "xray-gate-test-redis",
    }
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            "xray-port-config-test",
            "--file",
            str(ROOT / "deploy/compose/test.yml"),
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    services = yaml.safe_load(result.stdout)["services"]
    assert services["postgres"]["ports"][0]["published"] == "55435"
    assert services["redis"]["ports"][0]["published"] == "56382"
    volumes = yaml.safe_load(result.stdout)["volumes"]
    assert volumes["xray-test-postgres"]["name"] == "xray-gate-test-postgres"
    assert volumes["xray-test-redis"]["name"] == "xray-gate-test-redis"


def test_xray_asset_extractor_extracts_only_the_fixed_binary_member(tmp_path):
    archive = tmp_path / "xray.zip"
    output_dir = tmp_path / "runtime"
    output_dir.mkdir()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("xray", b"fixed xray test binary")
        bundle.writestr("unrelated.txt", b"must not be extracted")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/extract-xray-test-asset.py"),
            str(archive),
            str(output_dir),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (output_dir / "xray").read_bytes() == b"fixed xray test binary"
    assert not (output_dir / "unrelated.txt").exists()


def test_xray_asset_extractor_rejects_archives_without_the_fixed_binary(tmp_path):
    archive = tmp_path / "xray.zip"
    output_dir = tmp_path / "runtime"
    output_dir.mkdir()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("other", b"not the runtime")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/extract-xray-test-asset.py"),
            str(archive),
            str(output_dir),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "missing fixed xray binary member" in result.stderr


def test_xray_asset_fetch_does_not_require_system_unzip():
    script = (ROOT / "scripts/fetch-xray-test-asset.sh").read_text(encoding="utf-8")

    assert "command -v unzip" not in script
    assert "unzip -" not in script
    assert 'python3 "$root_dir/scripts/extract-xray-test-asset.py"' in script


def test_local_gate_resolves_service_urls_from_registered_port_overrides():
    script = (ROOT / "scripts/check-local.sh").read_text(encoding="utf-8")
    assignments = re.findall(
        r"(?m)^export XRAY_(?:TEST_DATABASE_URL|REDIS_URL)=.*$", script
    )
    assert len(assignments) == 2
    shell = "\n".join(
        [
            "set -euo pipefail",
            *assignments,
            '[[ "$XRAY_TEST_DATABASE_URL" == *@127.0.0.1:55435/xray_test ]]',
            '[[ "$XRAY_REDIS_URL" == redis://127.0.0.1:56382/0 ]]',
        ]
    )
    environment = {
        **os.environ,
        "XRAY_TEST_POSTGRES_PORT": "55435",
        "XRAY_TEST_REDIS_PORT": "56382",
    }
    environment.pop("XRAY_TEST_DATABASE_URL", None)
    environment.pop("XRAY_REDIS_URL", None)
    result = subprocess.run(
        ["bash", "-c", shell],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0


def test_ci_uses_dedicated_services_and_the_same_local_gate():
    workflow = yaml.load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    job = workflow["jobs"]["verify"]
    assert set(job["services"]) == {"postgres", "redis"}
    env = job["env"]
    assert "/xray_test" in env["XRAY_TEST_DATABASE_URL"]
    assert ":55432" in env["XRAY_TEST_DATABASE_URL"]
    assert ":56379/0" in env["XRAY_REDIS_URL"]
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "./scripts/check-local.sh" in commands
    assert "scripts/validate-acceptance.py" in commands
    lowered = str(workflow).lower()
    assert "aws_access_key" not in lowered
    assert "aliyun_access_key" not in lowered
    assert "real_cloud" not in lowered


def test_backup_tool_wrapper_is_executable():
    mode = os.stat(ROOT / "deploy/backup/run-in-tools.sh").st_mode
    assert mode & stat.S_IXUSR
