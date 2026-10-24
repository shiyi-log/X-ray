from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from apps.cloud_accounts.models import CloudAccount, CloudCredentialVersion
from apps.cloud_accounts.serializers import CloudAccountSerializer
from apps.identity.models import SuperAdmin
from apps.nodes import views as node_views
from apps.nodes.models import ManagedNode, NodePool
from common.regions import DEFAULT_REGION, normalize_region


def _authenticated_client():
    from datetime import timedelta

    from django.utils import timezone

    admin = SuperAdmin.objects.create_superuser("owner", "test-only-password")
    client = APIClient()
    session = client.session
    session["admin_id"] = str(admin.pk)
    session["session_version"] = admin.session_version
    session["absolute_expires_at"] = (timezone.now() + timedelta(hours=1)).isoformat()
    session["recent_auth_until"] = (timezone.now() + timedelta(minutes=5)).isoformat()
    session.save()
    return client


def test_normalize_region_defaults_blank_values_to_singapore():
    assert normalize_region("") == DEFAULT_REGION
    assert normalize_region("  ") == DEFAULT_REGION
    assert normalize_region(None) == DEFAULT_REGION
    assert normalize_region("eu-west-1") == "eu-west-1"


def test_cloud_account_create_accepts_blank_region_and_uses_singapore():
    name, region, raw = CloudAccountSerializer.validate_create(
        {
            "name": "demo",
            "provider": "aws_lightsail",
            "region": "",
            "credentials": {"access_key_id": "access", "secret_access_key": "secret"},
        }
    )
    assert name == "demo"
    assert region == DEFAULT_REGION
    assert raw["provider"] == "aws_lightsail"


@pytest.mark.django_db
def test_node_create_accepts_omitted_region_and_uses_singapore(monkeypatch):
    client = _authenticated_client()
    account = CloudAccount.objects.create(
        name="Fake AWS",
        provider="aws_lightsail",
        external_account_id="123456789012",
        credential_version=1,
    )
    credential = CloudCredentialVersion.objects.create(
        account=account,
        version=1,
        encrypted_credentials={"ciphertext": "test-only-opaque"},
        identity_verified_at=account.created_at,
    )
    pool = NodePool.objects.create(name=f"pool-{uuid4()}", quota=1)
    captured: dict[str, str] = {}
    original_reserve = node_views.reserve_node

    def reserve(*args, **kwargs):
        captured["region"] = kwargs["region"]
        return original_reserve(*args, **kwargs)

    monkeypatch.setattr(node_views, "reserve_node", reserve)
    operation = SimpleNamespace(
        pk=uuid4(), status="PENDING", target_type="node", target_id=uuid4()
    )
    monkeypatch.setattr(node_views.OperationService, "submit", lambda **_kwargs: operation)

    response = client.post(
        "/api/v1/nodes/",
        {
            "pool_id": str(pool.pk),
            "account_id": str(account.pk),
            "plan_id": "nano",
            "image_id": "debian-12",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert response.status_code == 202
    assert captured["region"] == DEFAULT_REGION
    assert ManagedNode.objects.get(pool=pool).region == DEFAULT_REGION
    assert credential.pk
