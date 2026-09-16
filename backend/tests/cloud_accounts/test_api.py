from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.cloud_accounts.models import CloudAccount


@pytest.fixture
def authenticated_client(db):
    from apps.identity.models import SuperAdmin

    admin = SuperAdmin.objects.create_superuser("owner", "test-only-password-A")
    client = APIClient()
    session = client.session
    session["admin_id"] = str(admin.pk)
    session["session_version"] = admin.session_version
    session["absolute_expires_at"] = (timezone.now() + timedelta(hours=1)).isoformat()
    session["recent_auth_until"] = (timezone.now() + timedelta(minutes=5)).isoformat()
    session.save()
    return client, admin


@pytest.mark.django_db
def test_cloud_account_list_never_returns_credentials(authenticated_client):
    client, admin = authenticated_client
    account = CloudAccount.objects.create(
        name="fake",
        provider="aws_lightsail",
        external_account_id="111111111111",
        credential_version=1,
    )
    response = client.get("/api/v1/cloud-accounts/")
    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == str(account.pk)
    assert "encrypted_credentials" not in response.json()
    assert "secret_access_key" not in response.json()


@pytest.mark.django_db
def test_cloud_account_delete_is_rejected(authenticated_client):
    client, account_admin = authenticated_client
    account = CloudAccount.objects.create(
        name="fake",
        provider="aws_lightsail",
        external_account_id="111111111111",
        credential_version=1,
    )
    response = client.delete(f"/api/v1/cloud-accounts/{account.pk}/")
    assert response.status_code == 405
    assert CloudAccount.objects.filter(pk=account.pk).exists()


@pytest.mark.django_db
def test_cloud_account_api_requires_authentication():
    response = APIClient().get("/api/v1/cloud-accounts/")
    assert response.status_code == 401
