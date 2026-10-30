from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.cloud_accounts.models import CloudAccount, CloudCredentialVersion
from apps.identity.models import SuperAdmin
from apps.nodes.models import ManagedNode, NodePool
from apps.operations.models import Operation, OperationStep
from apps.subscriptions.models import AccessProfile


@pytest.fixture
def admin_client(db):
    admin = SuperAdmin.objects.create_superuser("owner", "test-only-password")
    client = APIClient()
    session = client.session
    session["admin_id"] = str(admin.pk)
    session["session_version"] = admin.session_version
    session["absolute_expires_at"] = (timezone.now() + timedelta(hours=1)).isoformat()
    session["recent_auth_until"] = (timezone.now() + timedelta(minutes=5)).isoformat()
    session.save()
    return client, admin


@pytest.fixture
def resource_graph(admin_client):
    _client, admin = admin_client
    account = CloudAccount.objects.create(
        name="Fake AWS",
        provider="aws_lightsail",
        external_account_id="123456789012",
        credential_version=1,
        validated_at=timezone.now(),
        last_validation_code="OK",
    )
    credential = CloudCredentialVersion.objects.create(
        account=account,
        version=1,
        encrypted_credentials={"ciphertext": "test-only-opaque"},
        identity_verified_at=timezone.now(),
    )
    pool = NodePool.objects.create(name="primary", quota=3)
    node = ManagedNode.objects.create(
        pool=pool,
        cloud_account=account,
        cloud_credential_version=credential,
        region="us-east-1",
        plan_id="nano",
        image_id="debian-12",
        deterministic_name="xray-primary-1",
        operation_key=uuid4(),
    )
    operation = Operation.objects.create(
        admin=admin,
        kind="node.create",
        target_id=node.pk,
        params={"region": node.region},
        request_hash="a" * 64,
        idempotency_key=uuid4(),
        status="RUNNING",
        current_step="cloud.create",
    )
    OperationStep.objects.create(
        operation=operation,
        name="cloud.create",
        phase="cloud",
        status="RUNNING",
    )
    profile = AccessProfile.objects.create(name="phone")
    AuditEvent.objects.create(
        action="test.resource.created",
        target_type="node",
        target_id=str(node.pk),
        result="SUCCEEDED",
        actor=admin,
    )
    return account, pool, node, operation, profile


@pytest.mark.django_db
def test_management_collections_are_paginated_and_redacted(admin_client, resource_graph):
    client, _admin = admin_client
    account, pool, node, operation, profile = resource_graph
    expectations = {
        "/api/v1/node-pools/": str(pool.pk),
        "/api/v1/nodes/": str(node.pk),
        "/api/v1/operations/": str(operation.pk),
        "/api/v1/access-profiles/": str(profile.pk),
        "/api/v1/subscriptions/": None,
        "/api/v1/audit-events/": None,
    }
    for path, expected_id in expectations.items():
        response = client.get(path)
        assert response.status_code == 200, path
        body = response.json()
        assert set(body) >= {"items", "total", "page", "page_size"}
        if expected_id:
            assert body["items"][0]["id"] == expected_id
        if path == "/api/v1/nodes/":
            assert "pool_id" not in body["items"][0]
            assert body["items"][0]["traffic_state"] == "NO_DATA"
        assert "encrypted_credentials" not in response.content.decode()
        assert "test-only-opaque" not in response.content.decode()

    detail = client.get(f"/api/v1/operations/{operation.pk}/")
    assert detail.status_code == 200
    assert detail.json()["current_step"] == "cloud.create"
    assert detail.json()["steps"][0]["name"] == "cloud.create"
    assert detail.json()["can_cancel"] is True

    overview = client.get("/api/v1/overview")
    assert overview.status_code == 200
    assert overview.json()["counts"]["nodes"] == 1


@pytest.mark.django_db
def test_management_contract_requires_server_session():
    assert APIClient().get("/api/v1/nodes/").status_code == 401


@pytest.mark.django_db
def test_openapi_generation_contains_stable_operation_ids(tmp_path):
    target = tmp_path / "schema.yaml"
    call_command("spectacular", file=str(target), validate=True)
    schema = target.read_text(encoding="utf-8")
    assert "operationId: operations_retrieve" in schema
    assert "operationId: auth_session_retrieve" in schema
    assert "operationId: subscriptions_force_revoke_create" in schema
