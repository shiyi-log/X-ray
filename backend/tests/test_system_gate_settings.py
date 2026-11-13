from __future__ import annotations

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.identity.models import ProviderIdentityNetworkSetting, SuperAdmin
from common.errors import DomainError
from providers.base import SecretInput


@pytest.fixture
def admin(db):
    return SuperAdmin.objects.create_superuser("owner", "test-only-password")


@pytest.fixture
def admin_client(admin, settings):
    settings.XRAY_ENV = "test"
    settings.XRAY_LOCAL_ONE_CLICK_LOGIN = True
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auth/csrf", HTTP_HOST="127.0.0.1")
    assert csrf.status_code == 200
    client.credentials(HTTP_X_CSRFTOKEN=csrf.json()["csrf_token"])
    login = client.post(
        "/api/v1/auth/local-login", {}, format="json", HTTP_HOST="127.0.0.1"
    )
    assert login.status_code == 200
    return client


@pytest.mark.django_db
@override_settings(ALLOWED_HOSTS=["*"])
def test_system_get_preserves_contract_and_reports_environment_default(
    admin_client, monkeypatch
):
    monkeypatch.setenv("XRAY_ENABLE_PROVIDER_NETWORK", "yes")

    response = admin_client.get("/api/v1/system")

    assert response.status_code == 200
    body = response.json()
    assert {"version", "environment", "debug", "allowed_hosts", "csrf_trusted_origins"} <= set(
        body
    )
    assert body["provider_identity_network"] == {
        "enabled": True,
        "source": "ENVIRONMENT",
    }
    assert body["node_status_sync"] == {
        "enabled": False,
        "interval_minutes": 60,
        "last_scheduled_at": None,
        "source": "DEFAULT",
    }


@pytest.mark.django_db
def test_system_node_status_sync_setting_is_validated_and_audited(admin_client, admin):
    enabled = admin_client.patch(
        "/api/v1/system",
        {"node_status_sync_enabled": True},
        format="json",
    )
    assert enabled.status_code == 200
    assert enabled.json()["node_status_sync"]["enabled"] is True
    assert enabled.json()["node_status_sync"]["interval_minutes"] == 60

    interval = admin_client.patch(
        "/api/v1/system",
        {"node_status_sync_interval_minutes": 15},
        format="json",
    )
    assert interval.status_code == 200
    assert interval.json()["node_status_sync"]["interval_minutes"] == 15

    for value in (4, 1441, True, "15", None):
        response = admin_client.patch(
            "/api/v1/system",
            {"node_status_sync_interval_minutes": value},
            format="json",
        )
        assert response.status_code == 400

    from apps.identity.models import NodeStatusSyncSetting

    setting = NodeStatusSyncSetting.objects.get(singleton_key=1)
    assert (setting.enabled, setting.interval_minutes) == (True, 15)
    event = AuditEvent.objects.filter(action="system.node_status_sync.update").order_by("pk").last()
    assert event.actor == admin
    assert event.metadata["enabled"] is True
    assert event.metadata["interval_minutes"] == 15


@pytest.mark.django_db
def test_system_gate_patch_requires_admin_auth_and_csrf(admin):
    unauthenticated = APIClient(enforce_csrf_checks=True)
    csrf = unauthenticated.get("/api/v1/auth/csrf")
    unauthenticated.credentials(HTTP_X_CSRFTOKEN=csrf.json()["csrf_token"])
    denied_get = unauthenticated.get("/api/v1/system")
    denied_patch = unauthenticated.patch(
        "/api/v1/system",
        {"provider_identity_network_enabled": True},
        format="json",
    )
    assert denied_get.status_code == 401
    assert denied_patch.status_code == 401

    session_only = APIClient(enforce_csrf_checks=True)
    session = session_only.session
    session["admin_id"] = str(admin.pk)
    session["session_version"] = admin.session_version
    session.save()
    missing_csrf = session_only.patch(
        "/api/v1/system",
        {"provider_identity_network_enabled": True},
        format="json",
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "CSRF_FAILED"
    assert not ProviderIdentityNetworkSetting.objects.exists()


@pytest.mark.django_db
def test_system_gate_patch_persists_and_audits_without_cloud_calls(
    admin_client, admin, monkeypatch
):
    from apps.cloud_accounts import services as cloud_account_services

    def unexpected_cloud_call(*_args, **_kwargs):
        raise AssertionError("system setting changes must not call a cloud provider")

    monkeypatch.setattr(cloud_account_services, "reader_for_input", unexpected_cloud_call)
    monkeypatch.setenv("XRAY_ENABLE_PROVIDER_NETWORK", "1")

    disabled = admin_client.patch(
        "/api/v1/system",
        {"provider_identity_network_enabled": False},
        format="json",
    )
    assert disabled.status_code == 200
    assert disabled.json()["provider_identity_network"] == {
        "enabled": False,
        "source": "DATABASE",
    }
    assert ProviderIdentityNetworkSetting.objects.get().enabled is False

    unchanged = admin_client.patch(
        "/api/v1/system",
        {"provider_identity_network_enabled": False},
        format="json",
    )
    assert unchanged.status_code == 200
    assert AuditEvent.objects.filter(
        action="system.provider_identity_network.update"
    ).count() == 1

    enabled = admin_client.patch(
        "/api/v1/system",
        {"provider_identity_network_enabled": True},
        format="json",
    )
    assert enabled.status_code == 200
    assert enabled.json()["provider_identity_network"] == {
        "enabled": True,
        "source": "DATABASE",
    }

    events = list(
        AuditEvent.objects.filter(action="system.provider_identity_network.update")
        .order_by("pk")
    )
    assert len(events) == 2
    assert events[0].actor == admin
    assert events[0].metadata == {
        "previous_enabled": True,
        "previous_source": "ENVIRONMENT",
        "enabled": False,
        "source": "DATABASE",
    }
    assert events[1].metadata == {
        "previous_enabled": False,
        "previous_source": "DATABASE",
        "enabled": True,
        "source": "DATABASE",
    }
    assert all("credential" not in repr(event.metadata).lower() for event in events)
    assert ProviderIdentityNetworkSetting.objects.count() == 1


@pytest.mark.django_db
def test_system_gate_patch_rejects_unknown_and_non_boolean_values(admin_client):
    unknown = admin_client.patch(
        "/api/v1/system",
        {"provider_identity_network_enabled": True, "force": True},
        format="json",
    )
    non_boolean = admin_client.patch(
        "/api/v1/system",
        {"provider_identity_network_enabled": "true"},
        format="json",
    )
    assert unknown.status_code == 400
    assert non_boolean.status_code == 400
    assert not ProviderIdentityNetworkSetting.objects.exists()


@pytest.mark.django_db
def test_provider_input_gate_uses_env_fallback_and_database_override(monkeypatch):
    from providers import registry

    credentials = SecretInput(
        "aws_lightsail", {"access_key_id": "fake", "secret_access_key": "fake"}
    )
    factory_calls = []
    monkeypatch.setattr(
        registry,
        "_provider_for_credentials",
        lambda *args, **kwargs: factory_calls.append((args, kwargs)) or "fake-provider",
    )
    monkeypatch.setenv("XRAY_ENABLE_PROVIDER_NETWORK", "1")

    assert registry.provider_identity_network_setting() == {
        "enabled": True,
        "source": "ENVIRONMENT",
    }
    ProviderIdentityNetworkSetting.objects.create(singleton_key=1, enabled=False)
    assert registry.provider_identity_network_setting() == {
        "enabled": False,
        "source": "DATABASE",
    }
    with pytest.raises(DomainError) as denied:
        registry.provider_for_input(credentials, "us-east-1")
    assert denied.value.code == "CLOUD_NETWORK_DISABLED"
    assert factory_calls == []

    ProviderIdentityNetworkSetting.objects.filter(singleton_key=1).update(enabled=True)
    monkeypatch.setenv("XRAY_ENABLE_PROVIDER_NETWORK", "0")
    assert registry.provider_for_input(credentials, "us-east-1") == "fake-provider"
    assert len(factory_calls) == 1


@pytest.mark.django_db
def test_provider_input_gate_defaults_open_in_local_test(monkeypatch, settings):
    from providers import registry

    settings.XRAY_ENV = "test"
    monkeypatch.delenv("XRAY_ENABLE_PROVIDER_NETWORK", raising=False)
    assert registry.provider_identity_network_setting() == {
        "enabled": True,
        "source": "ENVIRONMENT",
    }


@pytest.mark.django_db
def test_provider_input_gate_can_be_explicitly_disabled_in_local_test(monkeypatch, settings):
    from providers import registry

    settings.XRAY_ENV = "test"
    monkeypatch.setenv("XRAY_ENABLE_PROVIDER_NETWORK", "0")

    assert registry.provider_identity_network_setting() == {
        "enabled": False,
        "source": "ENVIRONMENT",
    }


@pytest.mark.django_db
def test_provider_input_gate_defaults_closed_outside_local_test(monkeypatch, settings):
    from providers import registry

    settings.XRAY_ENV = "production"
    monkeypatch.delenv("XRAY_ENABLE_PROVIDER_NETWORK", raising=False)

    assert registry.provider_identity_network_setting() == {
        "enabled": False,
        "source": "ENVIRONMENT",
    }


@pytest.mark.django_db
def test_disabled_production_gate_directs_admin_to_system_setting(monkeypatch, settings):
    from providers import registry

    settings.XRAY_ENV = "production"
    monkeypatch.delenv("XRAY_ENABLE_PROVIDER_NETWORK", raising=False)
    credentials = SecretInput(
        "aws_lightsail", {"access_key_id": "fake", "secret_access_key": "fake"}
    )

    with pytest.raises(DomainError) as denied:
        registry.provider_for_input(credentials, "us-east-1")

    assert denied.value.code == "CLOUD_NETWORK_DISABLED"
    assert denied.value.status_code == 503
    assert denied.value.retryable is False
    assert "云身份校验联网已关闭" in denied.value.message
    assert "系统设置" in denied.value.message
    assert "本地环境" not in denied.value.message
