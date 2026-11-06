from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.identity.models import NodeStatusSyncSetting
from apps.nodes.models import ManagedNode
from apps.nodes.tasks import schedule_node_status_refreshes
from apps.operations.models import Operation
from apps.operations.services import OperationService


@pytest.mark.django_db
def test_scheduler_is_disabled_by_default(prepared_node):
    node, _ = prepared_node
    node.external_id = node.deterministic_name
    node.save(update_fields=["external_id", "updated_at"])

    result = schedule_node_status_refreshes()

    assert result["disabled"] is True
    assert not Operation.objects.filter(kind="node.refresh").exists()


@pytest.mark.django_db
def test_scheduler_waits_for_interval_then_submits_and_skips_inflight(prepared_node, admin):
    node, create_operation = prepared_node
    create_operation.status = "SUCCEEDED"
    create_operation.save(update_fields=["status", "updated_at"])
    node.external_id = node.deterministic_name
    node.provisioning_state = "PROVISIONED"
    node.save(update_fields=["external_id", "provisioning_state", "updated_at"])
    setting = NodeStatusSyncSetting.objects.create(
        enabled=True,
        interval_minutes=5,
        last_scheduled_at=timezone.now() - timedelta(minutes=5),
    )

    result = schedule_node_status_refreshes()

    assert result["scheduled"] == 1
    refresh = Operation.objects.get(kind="node.refresh", target_id=node.pk)
    assert refresh.status == "PENDING"
    assert refresh.cloud_credential_version_id == node.cloud_credential_version_id
    assert NodeStatusSyncSetting.objects.get(pk=setting.pk).last_scheduled_at is not None

    too_early = schedule_node_status_refreshes()
    assert too_early["scheduled"] == 0
    assert "due_at" in too_early

    refresh.status = "SUCCEEDED"
    refresh.save(update_fields=["status", "updated_at"])
    setting.last_scheduled_at = timezone.now() - timedelta(minutes=5)
    setting.save(update_fields=["last_scheduled_at", "updated_at"])
    result = schedule_node_status_refreshes()
    assert result["scheduled"] == 1

    second = ManagedNode.objects.create(
        pool=node.pool,
        cloud_account=node.cloud_account,
        cloud_credential_version=node.cloud_credential_version,
        region=node.region,
        plan_id=node.plan_id,
        image_id=node.image_id,
        deterministic_name=f"{node.deterministic_name}-second",
        operation_key=uuid4(),
        external_id="second-instance",
        provisioning_state="PROVISIONED",
    )
    OperationService.submit(
        kind="node.refresh",
        target_id=second.pk,
        params={"region": second.region, "account_id": str(second.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=admin,
        cloud_credential_version=second.cloud_credential_version,
    )
    setting.refresh_from_db()
    setting.last_scheduled_at = timezone.now() - timedelta(minutes=5)
    setting.save(update_fields=["last_scheduled_at", "updated_at"])

    result = schedule_node_status_refreshes()

    assert result["scheduled"] == 0
    assert result["skipped"] == 2


@pytest.mark.django_db
def test_scheduler_skips_node_with_inflight_lifecycle_operation(prepared_node, admin):
    node, create_operation = prepared_node
    create_operation.status = "SUCCEEDED"
    create_operation.save(update_fields=["status", "updated_at"])
    node.external_id = node.deterministic_name
    node.save(update_fields=["external_id", "updated_at"])
    NodeStatusSyncSetting.objects.create(
        enabled=True,
        interval_minutes=5,
        last_scheduled_at=timezone.now() - timedelta(minutes=5),
    )
    OperationService.submit(
        kind="node.reboot",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(node.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=admin,
        cloud_credential_version=node.cloud_credential_version,
    )

    result = schedule_node_status_refreshes()

    assert result["scheduled"] == 0
    assert result["skipped"] == 1
    assert not Operation.objects.filter(kind="node.refresh", target_id=node.pk).exists()
