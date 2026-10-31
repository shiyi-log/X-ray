from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from apps.cloud_accounts.models import CloudAccount, CloudCredentialVersion
from apps.cloud_accounts.serializers import CloudAccountSerializer
from apps.identity.models import SuperAdmin
from apps.nodes import views as node_views
from apps.nodes.models import ManagedNode, NodePool, NodePoolRegionAllocation
from common.errors import DomainError
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
    assert normalize_region("ap-east-1") == "ap-east-1"


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
def test_node_pool_create_and_patch_expose_normalized_region(cloud_account):
    from apps.nodes.quota import reserve_node

    client = _authenticated_client()

    created = client.post(
        "/api/v1/node-pools/",
        {"name": "Hong Kong pool", "quota": 2, "region": "  ap-east-1  "},
        format="json",
    )
    assert created.status_code == 201
    assert created.json()["region"] == "ap-east-1"
    assert created.json()["name"] == "IP"

    updated_allocation = client.post(
        "/api/v1/node-pools/",
        {"allocations": [{"region": "ap-east-1", "quota": 3}]},
        format="json",
    )
    assert updated_allocation.status_code == 200
    assert NodePool.objects.count() == 1

    pool_id = created.json()["id"]
    updated = client.patch(
        f"/api/v1/node-pools/{pool_id}/",
        {"region": "us-east-1"},
        format="json",
    )
    assert updated.status_code == 200
    assert updated.json()["region"] == "us-east-1"

    reserve_node(
        pool_id=pool_id,
        account_id=cloud_account.pk,
        region=None,
        plan_id="nano",
        image_id="debian-12",
        operation_key=uuid4(),
    )
    blocked = client.patch(
        f"/api/v1/node-pools/{pool_id}/",
        {"region": "ap-east-1"},
        format="json",
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "POOL_REGION_IN_USE"


@pytest.mark.django_db
def test_node_pool_creation_gate_is_explicit_and_survives_quota_edits():
    client = _authenticated_client()
    created = client.post(
        "/api/v1/node-pools/",
        {"region": "us-east-1", "quota": 2, "allow_create": False},
        format="json",
    )
    assert created.status_code == 201
    pool_id = created.json()["id"]
    assert created.json()["allow_create"] is False
    assert client.get("/api/v1/node-pools/").json()["items"][0]["allow_create"] is False

    quota_update = client.patch(
        f"/api/v1/node-pools/{pool_id}/", {"quota": 3}, format="json"
    )
    assert quota_update.status_code == 200
    assert quota_update.json()["allow_create"] is False

    allocation_update = client.post(
        "/api/v1/node-pools/",
        {"allocations": [{"region": "us-east-1", "quota": 4}]},
        format="json",
    )
    assert allocation_update.status_code == 200
    assert allocation_update.json()["allow_create"] is False

    enabled = client.patch(
        f"/api/v1/node-pools/{pool_id}/", {"allow_create": True}, format="json"
    )
    assert enabled.status_code == 200
    assert enabled.json()["allow_create"] is True

    invalid = client.patch(
        f"/api/v1/node-pools/{pool_id}/",
        {"quota": 5, "allow_create": "false"},
        format="json",
    )
    assert invalid.status_code == 400
    assert NodePool.objects.get(pk=pool_id).quota == 4
    assert NodePool.objects.get(pk=pool_id).allow_create is True


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


@pytest.mark.django_db
def test_node_create_inherits_custom_pool_region_and_rejects_mismatch(cloud_account, monkeypatch):
    from apps.nodes.quota import reserve_node

    pool = NodePool.objects.create(name=f"pool-{uuid4()}", region="ap-east-1", quota=1)
    node = reserve_node(
        pool.pk,
        account_id=cloud_account.pk,
        region=None,
        plan_id="nano",
        image_id="debian-12",
        operation_key=uuid4(),
    )
    assert node.region == "ap-east-1"

    with pytest.raises(DomainError) as caught:
        reserve_node(
            pool.pk,
            account_id=cloud_account.pk,
            region="us-east-1",
            plan_id="nano",
            image_id="debian-12",
            operation_key=uuid4(),
        )
    assert caught.value.code == "POOL_REGION_MISMATCH"


@pytest.mark.django_db
def test_quota_edit_preserves_paused_pool_until_gate_is_explicitly_enabled(cloud_account):
    from apps.nodes.quota import reserve_node, set_allocations, set_allow_create

    pool = NodePool.objects.create(
        name=f"paused-{uuid4()}", region="ap-east-1", quota=2, allow_create=False
    )
    with pytest.raises(DomainError) as paused:
        reserve_node(
            pool.pk,
            account_id=cloud_account.pk,
            region="ap-east-1",
            plan_id="nano",
            image_id="debian-12",
            operation_key=uuid4(),
        )
    assert paused.value.code == "POOL_CREATION_DISABLED"
    assert not pool.region_allocations.exists()

    still_paused = set_allocations(
        pool.pk, [{"region": "ap-east-1", "quota": 2}]
    )
    assert still_paused.allow_create is False
    reopened = set_allow_create(pool.pk, True)
    assert reopened.allow_create is True
    node = reserve_node(
        pool.pk,
        account_id=cloud_account.pk,
        region="ap-east-1",
        plan_id="nano",
        image_id="debian-12",
        operation_key=uuid4(),
    )
    assert node.region == "ap-east-1"


@pytest.mark.django_db
def test_node_pool_allocates_quota_per_supported_region(cloud_account):
    from apps.nodes.quota import reserve_node

    client = _authenticated_client()
    response = client.post(
        "/api/v1/node-pools/",
        {
            "name": "multi-region pool",
            "allocations": [
                {"region": "ap-southeast-1", "quota": 3},
                {"region": "ap-northeast-1", "quota": 2},
            ],
        },
        format="json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["quota"] == 5
    assert body["regions"] == ["ap-northeast-1", "ap-southeast-1"]
    assert {item["region"] for item in body["allocations"]} == {
        "ap-southeast-1",
        "ap-northeast-1",
    }

    pool = NodePool.objects.get(pk=body["id"])
    assert NodePoolRegionAllocation.objects.filter(pool=pool).count() == 2
    first = reserve_node(
        pool.pk,
        account_id=cloud_account.pk,
        region="ap-southeast-1",
        plan_id="nano",
        image_id="debian-12",
        operation_key=uuid4(),
    )
    second = reserve_node(
        pool.pk,
        account_id=cloud_account.pk,
        region="ap-northeast-1",
        plan_id="nano",
        image_id="debian-12",
        operation_key=uuid4(),
    )
    assert first.region == "ap-southeast-1"
    assert second.region == "ap-northeast-1"

    for _ in range(2):
        reserve_node(
            pool.pk,
            account_id=cloud_account.pk,
            region="ap-southeast-1",
            plan_id="nano",
            image_id="debian-12",
            operation_key=uuid4(),
        )

    with pytest.raises(DomainError) as exhausted:
        reserve_node(
            pool.pk,
            account_id=cloud_account.pk,
            region="ap-southeast-1",
            plan_id="nano",
            image_id="debian-12",
            operation_key=uuid4(),
        )
    assert exhausted.value.code == "POOL_QUOTA_EXCEEDED"

    lowered = client.patch(
        f"/api/v1/node-pools/{pool.pk}/",
        {
            "allocations": [
                {"region": "ap-southeast-1", "quota": 3},
                {"region": "ap-northeast-1", "quota": 2},
            ]
        },
        format="json",
    )
    assert lowered.status_code == 200

    blocked_update = client.patch(
        f"/api/v1/node-pools/{pool.pk}/",
        {
            "allocations": [
                {"region": "ap-southeast-1", "quota": 2},
                {"region": "ap-northeast-1", "quota": 2},
            ]
        },
        format="json",
    )
    assert blocked_update.status_code == 409
    assert blocked_update.json()["code"] == "QUOTA_BELOW_USAGE"

    blocked_remove = client.patch(
        f"/api/v1/node-pools/{pool.pk}/",
        {"allocations": [{"region": "ap-southeast-1", "quota": 3}]},
        format="json",
    )
    assert blocked_remove.status_code == 409
    assert blocked_remove.json()["code"] == "REGION_ALLOCATION_IN_USE"

    with pytest.raises(DomainError) as missing:
        reserve_node(
            pool.pk,
            account_id=cloud_account.pk,
            region=None,
            plan_id="nano",
            image_id="debian-12",
            operation_key=uuid4(),
        )
    assert missing.value.code == "POOL_REGION_REQUIRED"

    with pytest.raises(DomainError) as unallocated:
        reserve_node(
            pool.pk,
            account_id=cloud_account.pk,
            region="us-east-1",
            plan_id="nano",
            image_id="debian-12",
            operation_key=uuid4(),
        )
    assert unallocated.value.code == "POOL_REGION_UNALLOCATED"


@pytest.mark.django_db
def test_node_pool_rejects_unsupported_region_allocation():
    client = _authenticated_client()
    response = client.post(
        "/api/v1/node-pools/",
        {
            "name": "unsupported region pool",
            "allocations": [{"region": "eu-west-1", "quota": 1}],
        },
        format="json",
    )
    assert response.status_code == 400
    assert "unsupported region" in response.json()["message"]


@pytest.mark.django_db
def test_unsupported_region_allocation_is_preserved_only_for_existing_usage(cloud_account):
    client = _authenticated_client()
    pool = NodePool.objects.create(name=f"legacy-region-{uuid4()}", quota=3)

    rejected = client.patch(
        f"/api/v1/node-pools/{pool.pk}/",
        {"allocations": [{"region": "eu-west-1", "quota": 2}]},
        format="json",
    )
    assert rejected.status_code == 400
    assert "unsupported region" in rejected.json()["message"]

    allocation = NodePoolRegionAllocation.objects.create(
        pool=pool, region="eu-west-1", quota=3
    )
    retained_allocation = client.patch(
        f"/api/v1/node-pools/{pool.pk}/",
        {"allocations": [{"region": "eu-west-1", "quota": 2}]},
        format="json",
    )
    assert retained_allocation.status_code == 200
    allocation.refresh_from_db()
    assert allocation.quota == 2

    from apps.nodes.quota import reserve_node

    for _ in range(2):
        reserve_node(
            pool.pk,
            account_id=cloud_account.pk,
            region="eu-west-1",
            plan_id="nano",
            image_id="debian-12",
            operation_key=uuid4(),
        )

    retained = client.patch(
        f"/api/v1/node-pools/{pool.pk}/",
        {"allocations": [{"region": "eu-west-1", "quota": 2}]},
        format="json",
    )
    assert retained.status_code == 200

    below_usage = client.patch(
        f"/api/v1/node-pools/{pool.pk}/",
        {"allocations": [{"region": "eu-west-1", "quota": 1}]},
        format="json",
    )
    assert below_usage.status_code == 409
    assert below_usage.json()["code"] == "QUOTA_BELOW_USAGE"

    removed = client.patch(
        f"/api/v1/node-pools/{pool.pk}/",
        {"allocations": [{"region": "ap-southeast-1", "quota": 1}]},
        format="json",
    )
    assert removed.status_code == 409
    assert removed.json()["code"] == "REGION_ALLOCATION_IN_USE"

    allocation.delete()
    legacy_usage = client.patch(
        f"/api/v1/node-pools/{pool.pk}/",
        {"allocations": [{"region": "eu-west-1", "quota": 2}]},
        format="json",
    )
    assert legacy_usage.status_code == 200
    assert NodePoolRegionAllocation.objects.get(pool=pool).region == "eu-west-1"
