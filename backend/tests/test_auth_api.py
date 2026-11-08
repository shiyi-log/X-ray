from datetime import timedelta

import pyotp
import pytest
from django.contrib.auth.hashers import make_password
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import AdminSession, MFAChallenge, SuperAdmin


@pytest.fixture
def admin(db):
    return SuperAdmin.objects.create_superuser("owner", "test-only-password-A")


@pytest.fixture
def csrf_client():
    client = APIClient(enforce_csrf_checks=True)
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    client.credentials(HTTP_X_CSRFTOKEN=response.json()["csrf_token"])
    return client


def test_unauthenticated_session_reports_totp_disabled(csrf_client):
    body = csrf_client.get("/api/v1/auth/session").json()

    assert body["authenticated"] is False
    assert body["mfa_enabled"] is False


@pytest.mark.parametrize("environment", ["test", "production"])
def test_unbound_admin_can_log_in_with_password_without_mfa_setup(admin, csrf_client, environment):
    with override_settings(XRAY_ENV=environment, XRAY_DISABLE_TOTP=False):
        response = csrf_client.post(
            "/api/v1/auth/login",
            {"username": admin.username, "password": "test-only-password-A"},
            format="json",
        )
    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["mfa_enabled"] is False
    assert response.json()["totp_setup_required"] is False
    assert response.json()["recent_auth_until"] is None
    assert csrf_client.get("/api/v1/auth/session").json()["mfa_enabled"] is False
    assert csrf_client.get("/api/v1/system").status_code == 200
    assert not MFAChallenge.objects.filter(admin=admin).exists()


@override_settings(XRAY_DISABLE_TOTP=True)
def test_test_only_totp_bypass_starts_server_session(admin, csrf_client):
    response = csrf_client.post(
        "/api/v1/auth/login",
        {"username": admin.username, "password": "test-only-password-A"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["admin"]["username"] == admin.username
    assert csrf_client.get("/api/v1/auth/session").json()["authenticated"] is True


@override_settings(XRAY_ENV="production", XRAY_DISABLE_TOTP=True)
def test_totp_bypass_flag_is_ignored_outside_test_environment(admin, csrf_client):
    # An existing envelope must not be skipped even if legacy metadata is incomplete.
    admin.totp_secret_envelope = {"test-only": "unreadable-envelope"}
    admin.save(update_fields=["totp_secret_envelope"])
    response = csrf_client.post(
        "/api/v1/auth/login",
        {"username": admin.username, "password": "test-only-password-A"},
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("authenticated") is not True
    assert body["mfa_required"] is True
    assert body["totp_setup_required"] is False
    assert csrf_client.get("/api/v1/auth/session").json()["mfa_enabled"] is True


def test_optional_totp_enrollment_returns_codes_and_revokes_password_only_sessions(
    admin, csrf_client
):
    login = csrf_client.post(
        "/api/v1/auth/login",
        {"username": admin.username, "password": "test-only-password-A"},
        format="json",
    )
    assert login.json()["authenticated"] is True
    other_client = APIClient()
    assert other_client.post(
        "/api/v1/auth/login",
        {"username": admin.username, "password": "test-only-password-A"},
        format="json",
    ).json()["authenticated"] is True
    assert csrf_client.post(
        "/api/v1/auth/step-up", {"password": "test-only-password-A"}, format="json"
    ).status_code == 200
    setup = csrf_client.post(
        "/api/v1/auth/totp/setup", {}, format="json"
    )
    assert setup.status_code == 200
    challenge_id = setup.json()["challenge_id"]
    code = pyotp.TOTP(setup.json()["secret"]).now()
    confirmed = csrf_client.post(
        "/api/v1/auth/totp/confirm",
        {"challenge_id": challenge_id, "code": code},
        format="json",
    )
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["authenticated"] is True
    assert body["mfa_enabled"] is True
    assert len(body["recovery_codes"]) == 10
    assert SuperAdmin.objects.get(pk=admin.pk).totp_secret_envelope
    assert csrf_client.get("/api/v1/system").status_code == 200
    assert other_client.get("/api/v1/auth/session").json()["authenticated"] is False
    assert csrf_client.get("/api/v1/auth/session").json()["mfa_enabled"] is True
    assert csrf_client.post(
        "/api/v1/auth/totp/confirm",
        {"challenge_id": challenge_id, "code": code},
        format="json",
    ).status_code == 401


def test_optional_totp_enrollment_requires_authenticated_session(csrf_client):
    response = csrf_client.post("/api/v1/auth/totp/setup", {}, format="json")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.parametrize("recent_auth", [None, "invalid", "2026-11-08T00:00:00"])
def test_optional_totp_enrollment_requires_fresh_step_up(admin, csrf_client, recent_auth):
    csrf_client.post(
        "/api/v1/auth/login",
        {"username": admin.username, "password": "test-only-password-A"},
        format="json",
    )
    if recent_auth is not None:
        session = csrf_client.session
        session["recent_auth_until"] = recent_auth
        session.save()
    response = csrf_client.post("/api/v1/auth/totp/setup", {}, format="json")
    assert response.status_code == 403
    assert response.json()["code"] == "STEP_UP_REQUIRED"


def test_password_step_up_for_unbound_admin_expires_without_forcing_totp(admin, csrf_client):
    csrf_client.post(
        "/api/v1/auth/login",
        {"username": admin.username, "password": "test-only-password-A"},
        format="json",
    )
    invalid = csrf_client.post(
        "/api/v1/auth/step-up", {"password": "wrong-password"}, format="json"
    )
    assert invalid.status_code == 401
    assert invalid.json()["code"] == "STEP_UP_INVALID"
    assert csrf_client.get("/api/v1/auth/session").json()["recent_auth_until"] is None
    valid = csrf_client.post(
        "/api/v1/auth/step-up", {"password": "test-only-password-A"}, format="json"
    )
    assert valid.status_code == 200
    assert AdminSession.objects.get(admin=admin).last_step_up_at is not None
    session = csrf_client.session
    session["recent_auth_until"] = (timezone.now() - timedelta(seconds=1)).isoformat()
    session.save()
    expired = csrf_client.post("/api/v1/auth/totp/setup", {}, format="json")
    assert expired.status_code == 403
    assert expired.json()["code"] == "STEP_UP_REQUIRED"


def test_bound_admin_step_up_still_requires_totp(admin, csrf_client):
    from common.crypto import configured_secret_store

    secret = pyotp.random_base32()
    admin.totp_secret_envelope = configured_secret_store().encrypt(
        secret.encode(), purpose="control", aad=f"totp:{admin.pk}".encode()
    )
    admin.totp_confirmed_at = timezone.now()
    admin.save(update_fields=["totp_secret_envelope", "totp_confirmed_at"])
    login = csrf_client.post(
        "/api/v1/auth/login",
        {"username": admin.username, "password": "test-only-password-A"},
        format="json",
    )
    assert csrf_client.get("/api/v1/system").status_code == 401
    assert csrf_client.post(
        "/api/v1/auth/totp/verify",
        {"challenge_id": login.json()["challenge_id"], "code": pyotp.TOTP(secret).now()},
        format="json",
    ).status_code == 200
    assert csrf_client.get("/api/v1/auth/session").json()["mfa_enabled"] is True
    missing_code = csrf_client.post(
        "/api/v1/auth/step-up", {"password": "test-only-password-A"}, format="json"
    )
    assert missing_code.status_code == 401
    verified = csrf_client.post(
        "/api/v1/auth/step-up",
        {"password": "test-only-password-A", "code": pyotp.TOTP(secret).now()},
        format="json",
    )
    assert verified.status_code == 200
    assert csrf_client.post("/api/v1/auth/totp/setup", {}, format="json").status_code == 409


def test_totp_recovery_invalidates_pending_password_challenge(admin, csrf_client, monkeypatch):
    from io import StringIO

    from django.core.management import call_command

    from common.crypto import configured_secret_store

    admin.totp_secret_envelope = configured_secret_store().encrypt(
        pyotp.random_base32().encode(), purpose="control", aad=f"totp:{admin.pk}".encode()
    )
    admin.totp_confirmed_at = timezone.now()
    admin.save(update_fields=["totp_secret_envelope", "totp_confirmed_at"])
    login = csrf_client.post(
        "/api/v1/auth/login",
        {"username": admin.username, "password": "test-only-password-A"},
        format="json",
    )
    challenge_id = login.json()["challenge_id"]
    monkeypatch.setattr("builtins.input", lambda _prompt: "RESET-TOTP")
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "test-only-password-A")
    call_command("recover_superadmin", stdout=StringIO())
    stale_setup = csrf_client.post(
        "/api/v1/auth/totp/setup", {"challenge_id": challenge_id}, format="json"
    )
    assert stale_setup.status_code == 401
    assert stale_setup.json()["code"] == "MFA_CHALLENGE_EXPIRED"
    fresh = csrf_client.post(
        "/api/v1/auth/login",
        {"username": admin.username, "password": "test-only-password-A"},
        format="json",
    )
    assert fresh.json()["authenticated"] is True
    assert fresh.json()["mfa_enabled"] is False


def test_existing_totp_login_and_replay_is_rejected(admin, csrf_client):
    secret = pyotp.random_base32()
    from common.crypto import configured_secret_store

    admin.totp_secret_envelope = configured_secret_store().encrypt(
        secret.encode(), purpose="control", aad=f"totp:{admin.pk}".encode()
    )
    admin.totp_confirmed_at = timezone.now()
    admin.last_totp_step = -1
    admin.save(update_fields=["totp_secret_envelope", "totp_confirmed_at", "last_totp_step"])
    login = csrf_client.post(
        "/api/v1/auth/login",
        {"username": admin.username, "password": "test-only-password-A"},
        format="json",
    )
    challenge_id = login.json()["challenge_id"]
    code = pyotp.TOTP(secret).now()
    verified = csrf_client.post(
        "/api/v1/auth/totp/verify",
        {"challenge_id": challenge_id, "code": code},
        format="json",
    )
    assert verified.status_code == 200
    assert csrf_client.get("/api/v1/auth/session").json()["authenticated"] is True

    second = csrf_client.post(
        "/api/v1/auth/login",
        {"username": admin.username, "password": "test-only-password-A"},
        format="json",
    )
    replay = csrf_client.post(
        "/api/v1/auth/totp/verify",
        {"challenge_id": second.json()["challenge_id"], "code": code},
        format="json",
    )
    assert replay.status_code == 409
    assert replay.json()["code"] == "MFA_REPLAY"


def test_recovery_code_still_requires_challenge_and_is_one_time(admin, csrf_client):
    from common.crypto import configured_secret_store

    recovery_code = "test-only-recovery-code"
    admin.totp_secret_envelope = configured_secret_store().encrypt(
        pyotp.random_base32().encode(), purpose="control", aad=f"totp:{admin.pk}".encode()
    )
    admin.totp_confirmed_at = timezone.now()
    admin.recovery_code_hashes = [make_password(recovery_code)]
    admin.save(
        update_fields=["totp_secret_envelope", "totp_confirmed_at", "recovery_code_hashes"]
    )

    login = csrf_client.post(
        "/api/v1/auth/login",
        {"username": admin.username, "password": "test-only-password-A"},
        format="json",
    )
    assert csrf_client.post(
        "/api/v1/auth/recovery-code",
        {"challenge_id": "11111111-1111-4111-8111-111111111111", "code": recovery_code},
        format="json",
    ).status_code == 401
    challenge_id = login.json()["challenge_id"]
    verified = csrf_client.post(
        "/api/v1/auth/recovery-code",
        {"challenge_id": challenge_id, "code": recovery_code},
        format="json",
    )
    assert verified.status_code == 200
    assert verified.json()["authenticated"] is True
    assert csrf_client.get("/api/v1/auth/session").json()["authenticated"] is True
    assert AdminSession.objects.get(admin=admin).last_step_up_at is not None

    next_login = csrf_client.post(
        "/api/v1/auth/login",
        {"username": admin.username, "password": "test-only-password-A"},
        format="json",
    )
    replay = csrf_client.post(
        "/api/v1/auth/recovery-code",
        {"challenge_id": next_login.json()["challenge_id"], "code": recovery_code},
        format="json",
    )
    assert replay.status_code == 401
    assert replay.json()["code"] == "RECOVERY_INVALID"


def test_logout_all_invalidates_previous_session(admin, csrf_client):
    secret = pyotp.random_base32()
    from common.crypto import configured_secret_store

    admin.totp_secret_envelope = configured_secret_store().encrypt(
        secret.encode(), purpose="control", aad=f"totp:{admin.pk}".encode()
    )
    admin.totp_confirmed_at = timezone.now()
    admin.save(update_fields=["totp_secret_envelope", "totp_confirmed_at"])
    login = csrf_client.post(
        "/api/v1/auth/login",
        {"username": admin.username, "password": "test-only-password-A"},
        format="json",
    )
    csrf_client.post(
        "/api/v1/auth/totp/verify",
        {"challenge_id": login.json()["challenge_id"], "code": pyotp.TOTP(secret).now()},
        format="json",
    )
    assert csrf_client.get("/api/v1/system").status_code == 200
    logout_all = csrf_client.post("/api/v1/auth/logout-all", {}, format="json")
    assert logout_all.status_code == 200
    assert csrf_client.get("/api/v1/auth/session").json()["authenticated"] is False
    assert AdminSession.objects.filter(admin=admin, revoked_at__isnull=False).exists()


def test_csrf_is_required_for_login(admin):
    client = APIClient(enforce_csrf_checks=True)
    response = client.post(
        "/api/v1/auth/login",
        {"username": admin.username, "password": "test-only-password-A"},
        format="json",
    )
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"


def test_local_vite_origin_is_accepted_for_login(admin):
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auth/csrf", HTTP_HOST="127.0.0.1")
    client.credentials(
        HTTP_X_CSRFTOKEN=csrf.json()["csrf_token"],
        HTTP_ORIGIN="http://127.0.0.1:9528",
    )
    response = client.post(
        "/api/v1/auth/login",
        {"username": admin.username, "password": "test-only-password-A"},
        format="json",
        HTTP_HOST="127.0.0.1",
    )
    assert response.status_code == 200
    assert response.json().get("code") != "CSRF_FAILED"


@override_settings(XRAY_ENV="test", XRAY_LOCAL_ONE_CLICK_LOGIN=False)
def test_local_one_click_login_can_be_disabled(csrf_client):
    status = csrf_client.get(
        "/api/v1/auth/local-login/status", HTTP_HOST="127.0.0.1"
    )
    response = csrf_client.post(
        "/api/v1/auth/local-login", {}, format="json", HTTP_HOST="127.0.0.1"
    )

    assert status.status_code == 200
    assert status.json() == {"enabled": False}
    assert response.status_code == 404


@override_settings(XRAY_ENV="test", XRAY_LOCAL_ONE_CLICK_LOGIN=True)
def test_local_one_click_login_starts_server_session_without_step_up(admin, csrf_client):
    status = csrf_client.get(
        "/api/v1/auth/local-login/status", HTTP_HOST="127.0.0.1"
    )
    response = csrf_client.post(
        "/api/v1/auth/local-login", {}, format="json", HTTP_HOST="127.0.0.1"
    )

    assert status.json() == {"enabled": True}
    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["mfa_required"] is False
    assert response.json()["recent_auth_until"] is None
    assert response.json()["admin"]["username"] == admin.username
    session = csrf_client.get(
        "/api/v1/auth/session", HTTP_HOST="127.0.0.1"
    ).json()
    assert session["authenticated"] is True
    assert session["recent_auth_until"] is None
    record = AdminSession.objects.get(admin=admin)
    assert record.session_version == admin.session_version
    assert record.last_step_up_at is None
    assert not MFAChallenge.objects.filter(admin=admin).exists()


@override_settings(
    XRAY_ENV="test", XRAY_LOCAL_ONE_CLICK_LOGIN=True, ALLOWED_HOSTS=["*"]
)
def test_local_one_click_login_requires_loopback_host_and_socket_peer(admin, csrf_client):
    remote_status = csrf_client.get(
        "/api/v1/auth/local-login/status",
        HTTP_HOST="127.0.0.1",
        REMOTE_ADDR="192.0.2.10",
        HTTP_X_FORWARDED_FOR="127.0.0.1",
    )
    remote_post = csrf_client.post(
        "/api/v1/auth/local-login",
        {},
        format="json",
        HTTP_HOST="127.0.0.1",
        REMOTE_ADDR="192.0.2.10",
        HTTP_X_FORWARDED_FOR="127.0.0.1",
    )
    public_host_status = csrf_client.get(
        "/api/v1/auth/local-login/status",
        HTTP_HOST="example.com",
        REMOTE_ADDR="127.0.0.1",
    )
    public_host_post = csrf_client.post(
        "/api/v1/auth/local-login",
        {},
        format="json",
        HTTP_HOST="example.com",
        REMOTE_ADDR="127.0.0.1",
    )

    assert remote_status.json() == {"enabled": False}
    assert remote_post.status_code == 404
    assert public_host_status.json() == {"enabled": False}
    assert public_host_post.status_code == 404
    assert not AdminSession.objects.filter(admin=admin).exists()


@override_settings(XRAY_ENV="production", XRAY_LOCAL_ONE_CLICK_LOGIN=True)
def test_local_one_click_login_is_unavailable_outside_test_environment(csrf_client):
    status = csrf_client.get(
        "/api/v1/auth/local-login/status", HTTP_HOST="127.0.0.1"
    )
    response = csrf_client.post(
        "/api/v1/auth/local-login", {}, format="json", HTTP_HOST="127.0.0.1"
    )

    assert status.json() == {"enabled": False}
    assert response.status_code == 404


@override_settings(XRAY_ENV="test", XRAY_LOCAL_ONE_CLICK_LOGIN=True)
def test_local_one_click_login_post_requires_csrf():
    client = APIClient(enforce_csrf_checks=True)
    response = client.post(
        "/api/v1/auth/local-login",
        {},
        format="json",
        HTTP_HOST="127.0.0.1",
    )

    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"
