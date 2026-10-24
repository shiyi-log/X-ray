import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from rest_framework.test import APIClient

from apps.identity.models import AdminSession, SuperAdmin


@pytest.mark.django_db
def test_sync_env_superadmin_creates_and_updates_local_admin(monkeypatch):
    monkeypatch.setenv("XRAY_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("XRAY_ADMIN_PASSWORD", "local-development-password")

    call_command("sync_env_superadmin", verbosity=0)
    admin = SuperAdmin.objects.get()
    assert admin.username == "admin"
    assert admin.check_password("local-development-password")

    monkeypatch.setenv("XRAY_ADMIN_USERNAME", "developer")
    monkeypatch.setenv("XRAY_ADMIN_PASSWORD", "updated-development-password")
    call_command("sync_env_superadmin", verbosity=0)
    admin.refresh_from_db()
    assert admin.username == "developer"
    assert admin.check_password("updated-development-password")


@pytest.mark.django_db
def test_sync_env_superadmin_is_idempotent_when_credentials_are_unchanged(monkeypatch):
    monkeypatch.setenv("XRAY_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("XRAY_ADMIN_PASSWORD", "local-development-password")

    call_command("sync_env_superadmin", verbosity=0)
    admin = SuperAdmin.objects.get()
    original = (admin.password, admin.session_version, admin.updated_at)
    call_command("sync_env_superadmin", verbosity=0)
    admin.refresh_from_db()

    assert (admin.password, admin.session_version, admin.updated_at) == original


@pytest.mark.django_db
def test_sync_env_superadmin_restores_local_admin_flags(monkeypatch):
    monkeypatch.setenv("XRAY_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("XRAY_ADMIN_PASSWORD", "local-development-password")
    call_command("sync_env_superadmin", verbosity=0)
    admin = SuperAdmin.objects.get()
    admin.is_active = False
    admin.is_staff = False
    admin.is_superuser = False
    admin.save(update_fields=["is_active", "is_staff", "is_superuser", "updated_at"])

    call_command("sync_env_superadmin", verbosity=0)
    admin.refresh_from_db()
    assert admin.is_active and admin.is_staff and admin.is_superuser


@override_settings(XRAY_DISABLE_TOTP=True, XRAY_ENV="test")
@pytest.mark.django_db
def test_sync_env_superadmin_revokes_sessions_after_credential_change(monkeypatch):
    monkeypatch.setenv("XRAY_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("XRAY_ADMIN_PASSWORD", "local-development-password")
    call_command("sync_env_superadmin", verbosity=0)

    client = APIClient()
    csrf = client.get("/api/v1/auth/csrf")
    client.credentials(HTTP_X_CSRFTOKEN=csrf.json()["csrf_token"])
    login = client.post(
        "/api/v1/auth/login",
        {"username": "admin", "password": "local-development-password"},
        format="json",
    )
    assert login.status_code == 200
    assert login.json()["authenticated"] is True
    assert client.get("/api/v1/system").status_code == 200

    monkeypatch.setenv("XRAY_ADMIN_PASSWORD", "updated-development-password")
    call_command("sync_env_superadmin", verbosity=0)

    assert client.get("/api/v1/auth/session").json()["authenticated"] is False
    assert client.get("/api/v1/system").status_code == 401
    assert AdminSession.objects.filter(revoked_at__isnull=False).exists()


@pytest.mark.parametrize(
    ("settings_overrides", "env_values"),
    [
        ({"XRAY_ENV": "production"}, {"XRAY_ADMIN_USERNAME": "admin", "XRAY_ADMIN_PASSWORD": "local-development-password"}),
        ({}, {"XRAY_ADMIN_USERNAME": "admin"}),
        ({}, {"XRAY_ADMIN_USERNAME": "admin", "XRAY_ADMIN_PASSWORD": "too-short"}),
    ],
)
@pytest.mark.django_db
def test_sync_env_superadmin_rejects_unsafe_or_incomplete_configuration(
    monkeypatch, settings_overrides, env_values
):
    for key in ("XRAY_ADMIN_USERNAME", "XRAY_ADMIN_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env_values.items():
        monkeypatch.setenv(key, value)

    with override_settings(**settings_overrides):
        with pytest.raises(CommandError):
            call_command("sync_env_superadmin", verbosity=0)
