from __future__ import annotations

import os
import stat
import subprocess
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
