from __future__ import annotations

import pytest

from apps.identity.models import NodeAutomationSetting
from apps.nodes.models import ManagedNode, NodeResource
from apps.nodes.quota import set_allocations
from apps.nodes.tasks import schedule_node_pool_sync
from apps.operations import handlers
from apps.operations.models import Operation
from providers.base import AccountRef

from .fakes import FakeCloudProvider


@pytest.mark.django_db
def test_pool_sync_create_runs_through_operation_handler_and_fake_provider(
    prepared_node, monkeypatch
):
    existing_node, _existing_create = prepared_node
    pool = existing_node.pool
    set_allocations(pool.pk, [{"region": existing_node.region, "quota": 2}])
    NodeAutomationSetting.objects.create(
        pool_sync_enabled=True,
        pool_sync_creation_templates=[
            {
                "region": existing_node.region,
                "cloud_account_id": str(existing_node.cloud_account_id),
                "plan_id": "nano",
                "image_id": "debian-12",
            }
        ],
    )

    scheduled = schedule_node_pool_sync()

    assert scheduled["created"] == 1
    created_node = ManagedNode.objects.exclude(pk=existing_node.pk).get(pool=pool)
    create_operation = Operation.objects.get(
        kind="node.create", target_id=created_node.pk
    )

    from apps.nodes.lifecycle import NodeLifecycle

    providers = {}

    def build_provider(node, authorizer):
        provider = providers.get(node.pk)
        if provider is None:
            account = AccountRef(
                node.cloud_account_id,
                node.cloud_account.provider,
                node.cloud_account.external_account_id,
                node.cloud_credential_version.version,
            )
            provider = FakeCloudProvider(account, node.region, authorizer=authorizer)
            providers[node.pk] = provider
        else:
            provider.authorizer = authorizer
        return provider

    lifecycle = NodeLifecycle(provider_factory=build_provider)
    monkeypatch.setattr(handlers, "NodeLifecycle", lambda: lifecycle)

    result = handlers.handle_operation(str(create_operation.pk))

    created_node.refresh_from_db()
    create_operation.refresh_from_db()
    assert result["status"] == "SUCCEEDED"
    assert create_operation.status == "SUCCEEDED"
    assert created_node.external_id == created_node.deterministic_name
    assert created_node.provisioning_state == "PROVISIONED"
    assert created_node.addresses == [
        {
            "value": "192.0.2.10",
            "family": 4,
            "kind": "dynamic",
            "resource_id": created_node.deterministic_name,
        }
    ]
    assert NodeResource.objects.filter(
        node=created_node,
        kind="instance",
        external_id=created_node.deterministic_name,
        ownership_tags={
            "xray-manager": "true",
            "xray-node": str(created_node.pk),
            "xray-operation": str(create_operation.idempotency_key),
        },
        cost_status="ACTIVE",
    ).exists()
    assert providers[created_node.pk].create_calls == 1
