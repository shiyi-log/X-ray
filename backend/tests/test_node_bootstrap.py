from uuid import uuid4

import pytest

from apps.nodes.models import NodeProtocol
from apps.operations.models import Operation, OperationStep
from apps.operations.services import OperationService


def _provisioned(node, operation):
    node.external_id = node.deterministic_name
    node.raw_cloud_state = "running"
    node.addresses = [{"value": "192.0.2.20", "family": 4, "kind": "dynamic"}]
    node.provisioning_state = "PROVISIONED"
    node.save(
        update_fields=[
            "external_id",
            "raw_cloud_state",
            "addresses",
            "provisioning_state",
            "updated_at",
        ]
    )
    operation.status = "SUCCEEDED"
    operation.save(update_fields=["status", "updated_at"])


@pytest.mark.django_db
def test_bootstrap_scheduler_creates_one_operation_for_provisioned_node(prepared_node):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_node_bootstrap

    node, create_operation = prepared_node
    _provisioned(node, create_operation)
    NodeAutomationSetting.objects.create(pool_sync_enabled=True)

    first = schedule_node_bootstrap()
    second = schedule_node_bootstrap()

    assert first == {"scheduled": 1, "skipped": 0}
    assert second == {"scheduled": 0, "skipped": 1}
    bootstrap = Operation.objects.get(kind="node.bootstrap", target_id=node.pk)
    assert bootstrap.params["region"] == node.region
    assert bootstrap.params["account_id"] == str(node.cloud_account_id)


@pytest.mark.django_db
def test_bootstrap_stops_before_protocol_or_subscription_changes(prepared_node):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_node_bootstrap
    from apps.operations.handlers import handle_operation
    from apps.subscriptions.models import AccessProfile, NodeCredential
    from apps.subscriptions.tokens import TokenService

    node, create_operation = prepared_node
    _provisioned(node, create_operation)
    NodeAutomationSetting.objects.create(pool_sync_enabled=True)
    profile = AccessProfile.objects.create(name="bootstrap-blocked")
    issued = TokenService.issue(profile.pk)
    revision_before = profile.subscription.current_revision_id
    generation_before = node.desired_generation
    bootstrap = OperationService.submit(
        kind="node.bootstrap",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(node.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=create_operation.admin,
        cloud_credential_version=node.cloud_credential_version,
    )

    handle_operation(str(bootstrap.pk))

    node.refresh_from_db()
    bootstrap.refresh_from_db()
    profile.subscription.refresh_from_db()
    assert bootstrap.status == "NEEDS_RECONCILIATION"
    assert bootstrap.error_code == "BOOTSTRAP_INSTALLER_UNAVAILABLE"
    assert node.provisioning_state == "PROVISIONED"
    assert node.desired_generation == generation_before
    assert not NodeProtocol.objects.filter(node=node).exists()
    assert not NodeCredential.objects.filter(node=node).exists()
    assert revision_before is None
    assert profile.subscription.current_revision_id is None
    assert issued.subscription_id == profile.subscription.pk
    assert OperationStep.objects.filter(
        operation=bootstrap, name="bootstrap.preflight", status="BLOCKED", attempt=1
    ).exists()

    assert schedule_node_bootstrap() == {"scheduled": 0, "skipped": 1}
    assert Operation.objects.filter(kind="node.bootstrap", target_id=node.pk).count() == 1

    retried = OperationService.retry(bootstrap.pk, admin=create_operation.admin)
    assert retried.status == "RETRY_PENDING"
    handle_operation(str(bootstrap.pk))
    retried.refresh_from_db()
    assert retried.status == "NEEDS_RECONCILIATION"
    assert Operation.objects.filter(kind="node.bootstrap", target_id=node.pk).count() == 1
    assert OperationStep.objects.filter(
        operation=bootstrap, name="bootstrap.preflight", status="BLOCKED"
    ).count() == 2


@pytest.mark.django_db
def test_bootstrap_rejects_wrong_account_binding_without_side_effects(prepared_node):
    from apps.nodes.bootstrap import NodeBootstrapService

    node, create_operation = prepared_node
    _provisioned(node, create_operation)
    bootstrap = OperationService.submit(
        kind="node.bootstrap",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(uuid4())},
        key=uuid4(),
        preview_id=None,
        admin=create_operation.admin,
        cloud_credential_version=node.cloud_credential_version,
    )

    NodeBootstrapService.run(bootstrap.pk)

    node.refresh_from_db()
    bootstrap.refresh_from_db()
    assert bootstrap.status == "FAILED"
    assert bootstrap.error_code == "OPERATION_TARGET_MISMATCH"
    assert node.provisioning_state == "PROVISIONED"
    assert not NodeProtocol.objects.filter(node=node).exists()
