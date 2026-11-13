from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_only_gateway_publishes_ports_and_internal_networks_stay_internal(environment):
    document = yaml.safe_load(
        (ROOT / f"deploy/compose/{environment}.yml").read_text(encoding="utf-8")
    )
    services = document["services"]
    publishers = {name for name, service in services.items() if service.get("ports")}
    assert publishers == {"gateway"}
    for name in ("control", "public-app", "data", "queue"):
        assert document["networks"][name]["internal"] is True
    assert set(services["gateway"]["networks"]) == {"edge", "control", "public-app"}
    assert set(services["subscription-api"]["networks"]) == {"public-app", "data"}
    assert "control" not in services["subscription-api"]["networks"]
    assert "data" not in services["gateway"]["networks"]
    assert "queue" not in services["gateway"]["networks"]


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_release_tools_are_not_persistent_services(environment):
    document = yaml.safe_load(
        (ROOT / f"deploy/compose/{environment}.yml").read_text(encoding="utf-8")
    )
    services = document["services"]
    assert services["database-bootstrap"]["profiles"] == ["release"]
    assert services["migrator"]["profiles"] == ["release"]
    assert services["migrator"]["secrets"] == [
        "django_secret_key",
        "control_master_key",
        "subscription_master_key",
        "owner_db_password",
    ]
    assert "cloud_credentials" not in services["migrator"]["secrets"]


def test_proxy_overwrites_forwarded_identity_and_public_path_does_not_log_token():
    admin = (ROOT / "deploy/nginx/admin.conf").read_text(encoding="utf-8")
    subscription = (ROOT / "deploy/nginx/subscription.conf").read_text(encoding="utf-8")
    for content in (admin, subscription):
        assert "proxy_set_header X-Forwarded-For $remote_addr;" in content
        assert "proxy_set_header X-Forwarded-Proto https;" in content
    assert "access_log off;" in subscription
    assert 'location ~ "^/s/[A-Za-z0-9_-]{43}$"' in subscription
    assert "/api/" not in subscription


def test_database_roles_keep_subscription_process_out_of_control_tables():
    sql = (ROOT / "deploy/postgres/roles.sql").read_text(encoding="utf-8")
    assert "xray_subscription_reader" in sql
    assert "subscriptions_revocationtombstone" in sql
    assert "cloud_accounts_cloudcredentialversion" in sql
    assert "REVOKE SELECT, INSERT, UPDATE, DELETE" in sql
    assert "audit_auditevent" in sql
