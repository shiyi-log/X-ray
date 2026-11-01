from datetime import timedelta
from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from apps.nodes.models import ManagedNode
from apps.operations.models import Operation, OutboxEvent


def _client_for_admin(admin):
    from django.utils import timezone

    client = APIClient()
    session = client.session
    session["admin_id"] = str(admin.pk)
    session["session_version"] = admin.session_version
    session["absolute_expires_at"] = (timezone.now() + timedelta(hours=1)).isoformat()
    session["recent_auth_until"] = (timezone.now() + timedelta(minutes=5)).isoformat()
    session.save()
    return client


@pytest.mark.django_db
def test_node_refresh_submits_idempotent_read_operation(prepared_node, admin):
    node, _create_operation = prepared_node
    node.external_id = node.deterministic_name
    node.provisioning_state = "PROVISIONED"
    node.save(update_fields=["external_id", "provisioning_state", "updated_at"])
    client = _client_for_admin(admin)
    key = str(uuid4())

    response = client.post(
        f"/api/v1/nodes/{node.pk}/refresh/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )
    repeated = client.post(
        f"/api/v1/nodes/{node.pk}/refresh/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )

    assert response.status_code == 202
    assert repeated.status_code == 202
    assert response.json()["operation_id"] == repeated.json()["operation_id"]
    operation = Operation.objects.get(pk=response.json()["operation_id"])
    assert operation.kind == "node.refresh"
    assert OutboxEvent.objects.filter(operation=operation).count() == 1


@pytest.mark.django_db
def test_node_refresh_rejects_unprovisioned_records(prepared_node, admin):
    node, _create_operation = prepared_node
    response = _client_for_admin(admin).post(
        f"/api/v1/nodes/{node.pk}/refresh/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "NODE_NOT_PROVISIONED"
    assert ManagedNode.objects.get(pk=node.pk).consumes_quota is True
