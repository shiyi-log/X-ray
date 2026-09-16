import pyotp
import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import AdminSession, SuperAdmin


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


def test_password_only_cannot_access_management(admin, csrf_client):
    response = csrf_client.post(
        "/api/v1/auth/login",
        {"username": admin.username, "password": "test-only-password-A"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["authenticated"] if "authenticated" in response.json() else True
    assert csrf_client.get("/api/v1/auth/session").json()["authenticated"] is False
    assert csrf_client.get("/api/v1/system").status_code in (401, 403)


def test_first_login_binds_totp_and_returns_recovery_codes(admin, csrf_client):
    login = csrf_client.post(
        "/api/v1/auth/login",
        {"username": admin.username, "password": "test-only-password-A"},
        format="json",
    )
    challenge_id = login.json()["challenge_id"]
    setup = csrf_client.post(
        "/api/v1/auth/totp/setup", {"challenge_id": challenge_id}, format="json"
    )
    assert setup.status_code == 200
    code = pyotp.TOTP(setup.json()["secret"]).now()
    confirmed = csrf_client.post(
        "/api/v1/auth/totp/confirm",
        {"challenge_id": challenge_id, "code": code},
        format="json",
    )
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["authenticated"] is True
    assert len(body["recovery_codes"]) == 10
    assert SuperAdmin.objects.get(pk=admin.pk).totp_secret_envelope
    assert csrf_client.get("/api/v1/system").status_code == 200


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
