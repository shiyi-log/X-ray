from __future__ import annotations

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
    assert "backup.sh" in release
    assert "migrate --check" in release
    assert "pg_restore" not in rollback
    assert "restore.sh" not in rollback
    assert "REVOCATION" in rollback
    assert "--config" in preflight


def test_docker_context_excludes_reference_data_and_secret_material():
    content = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    required = {"archive/", ".git/", ".env", "**/secrets/", "backups/", "runtime/"}
    assert required.issubset(set(content.splitlines()))
