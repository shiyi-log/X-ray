from uuid import uuid4

import pytest

from providers.base import AccountRef

from .fakes import FakeCloudProvider


def make_lifecycle(node, *, probe=None):
    from apps.nodes.lifecycle import NodeLifecycle

    holder = {}

    def build(candidate, authorizer):
        if "provider" not in holder:
            account = AccountRef(
                candidate.cloud_account_id,
                candidate.cloud_account.provider,
                candidate.cloud_account.external_account_id,
                candidate.cloud_credential_version.version,
            )
            holder["provider"] = FakeCloudProvider(account, candidate.region, authorizer=authorizer)
        else:
            holder["provider"].authorizer = authorizer
        return holder["provider"]

    return NodeLifecycle(provider_factory=build, isolation_probe=probe), holder


def test_long_provider_operation_poll_renews_claim(monkeypatch):
    from apps.nodes import lifecycle as lifecycle_module
    from providers.base import AccountRef, ResourceRef

    class Clock:
        value = 0.0

        def monotonic(self):
            return self.value

        def sleep(self, seconds):
            self.value += seconds

    clock = Clock()
    monkeypatch.setattr(lifecycle_module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(lifecycle_module.time, "sleep", clock.sleep)
    monkeypatch.setattr(lifecycle_module, "PROVIDER_OPERATION_TIMEOUT_SECONDS", 180)
    monkeypatch.setattr(lifecycle_module, "LIFECYCLE_OPERATION_LEASE_SECONDS", 60)
    account = AccountRef(uuid4(), "aws_lightsail", "test-account", 1)
    resource = ResourceRef(account, "ap-southeast-1", "node-1")
    provider = FakeCloudProvider(account, resource.region, authorizer=None)
    provider.reboot_operation_statuses = ["IN_PROGRESS", "IN_PROGRESS", "SUCCEEDED"]
    original_get_status = provider.get_operation_status

    def delayed_get_status(*args, **kwargs):
        clock.value += 16
        return original_get_status(*args, **kwargs)

    provider.get_operation_status = delayed_get_status
    renewals = []

    status, error = lifecycle_module.NodeLifecycle._wait_for_provider_operation(
        provider,
        "fake-reboot-operation",
        resource,
        "reboot",
        renew_claim_callback=lambda: renewals.append(clock.value),
    )

    assert status == "SUCCEEDED"
    assert error == ""
    assert renewals


def test_long_instance_readback_renews_claim(monkeypatch):
    from apps.nodes import lifecycle as lifecycle_module
    from providers.base import AccountRef, ResourceRef

    class Clock:
        value = 0.0

        def monotonic(self):
            return self.value

        def sleep(self, seconds):
            self.value += seconds

    clock = Clock()
    monkeypatch.setattr(lifecycle_module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(lifecycle_module.time, "sleep", clock.sleep)
    monkeypatch.setattr(lifecycle_module, "INSTANCE_READBACK_TIMEOUT_SECONDS", 180)
    monkeypatch.setattr(lifecycle_module, "LIFECYCLE_OPERATION_LEASE_SECONDS", 60)
    account = AccountRef(uuid4(), "aws_lightsail", "test-account", 1)
    resource = ResourceRef(account, "ap-southeast-1", "node-1")
    provider = FakeCloudProvider(account, resource.region, authorizer=None)
    provider.instances[resource.resource_id] = provider._instance(
        resource.resource_id,
        {"xray-manager": "true", "xray-node": "node", "xray-operation": "op"},
    )
    original_get_instance = provider.get_instance

    def delayed_get_instance(resource):
        clock.value += 16
        return original_get_instance(resource)

    provider.get_instance = delayed_get_instance
    renewals = []

    instance, error = lifecycle_module.NodeLifecycle._wait_for_instance_readback(
        provider,
        resource,
        expected_state="running",
        renew_claim_callback=lambda: renewals.append(clock.value),
    )

    assert instance is not None
    assert error == ""
    assert renewals


def make_delete_operation(admin, node):
    from apps.operations.services import ActionPreviewService, OperationService

    params = {
        "region": node.region,
        "account_id": str(node.cloud_account_id),
        "confirmation": "确认删除服务器",
    }
    snapshot = {
        "external_id": node.external_id,
        "region": node.region,
        "account_id": str(node.cloud_account_id),
        "addresses": list(node.addresses or []),
        "desired_state": node.desired_state,
        "desired_generation": node.desired_generation,
    }
    key = uuid4()
    preview = ActionPreviewService.create(
        admin=admin,
        kind="node.delete",
        target_id=node.pk,
        params=params,
        snapshot=snapshot,
        required_phrase="确认删除服务器",
    )
    return OperationService.submit(
        kind="node.delete",
        target_id=node.pk,
        params=params,
        key=key,
        preview_id=preview.pk,
        admin=admin,
        cloud_credential_version=node.cloud_credential_version,
    )


def provision_node_for_delete(node):
    node.external_id = node.deterministic_name
    node.addresses = [{"value": "192.0.2.10", "family": 4, "kind": "dynamic"}]
    node.provisioning_state = "PROVISIONED"
    node.save(update_fields=["external_id", "addresses", "provisioning_state", "updated_at"])


def make_node_action(admin, node, action):
    from apps.operations.services import OperationService

    return OperationService.submit(
        kind=f"node.{action}",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(node.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=admin,
        cloud_credential_version=node.cloud_credential_version,
    )


def provision_node_for_action(node):
    node.external_id = node.deterministic_name
    node.addresses = [{"value": "192.0.2.10", "family": 4, "kind": "dynamic"}]
    node.raw_cloud_state = "stopped"
    node.provisioning_state = "READY"
    node.save(
        update_fields=[
            "external_id",
            "addresses",
            "raw_cloud_state",
            "provisioning_state",
            "updated_at",
        ]
    )


@pytest.mark.django_db
def test_fake_lifecycle_adopts_read_after_write(prepared_node):
    node, operation = prepared_node
    lifecycle, holder = make_lifecycle(node)

    lifecycle.create(node.pk, operation_id=operation.pk)

    node.refresh_from_db()
    operation.refresh_from_db()
    assert holder["provider"].create_calls == 1
    assert node.external_id == node.deterministic_name
    assert node.provisioning_state == "PROVISIONED"
    assert node.resources.filter(kind="instance", external_id=node.external_id).exists()
    assert operation.status == "SUCCEEDED"


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["unprovisioned", "deleted"])
def test_start_worker_rejects_unavailable_instance_without_provider_write(
    prepared_node, admin, state
):
    from apps.operations.services import OperationService

    node, _create_operation = prepared_node
    if state == "deleted":
        node.external_id = "deleted-instance"
        node.desired_state = "DELETED"
        node.save(update_fields=["external_id", "desired_state", "updated_at"])
    operation = OperationService.submit(
        kind="node.start",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(node.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=admin,
        cloud_credential_version=node.cloud_credential_version,
    )
    lifecycle, holder = make_lifecycle(node)

    lifecycle.dispatch("start", node.pk, operation_id=operation.pk)

    operation.refresh_from_db()
    assert operation.status == "FAILED"
    assert operation.error_code == "NODE_NOT_PROVISIONED"
    assert holder == {}


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["start", "reboot"])
def test_start_and_reboot_persist_exact_readback_and_changed_addresses(
    prepared_node, admin, monkeypatch, action
):
    from providers.base import Address

    node, _create_operation = prepared_node
    provision_node_for_action(node)
    operation = make_node_action(admin, node, action)
    lifecycle, holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        },
        state="stopped",
    )
    provider.addresses_after_lifecycle_write = (
        Address("198.51.100.20", 4, "dynamic", node.external_id),
    )
    refresh = []
    monkeypatch.setattr(
        "apps.subscriptions.publishing.Publisher.refresh_node_address",
        lambda node_id: refresh.append(node_id) or {"published": 1, "failed": 0},
    )

    lifecycle.dispatch(action, node.pk, operation_id=operation.pk)

    node.refresh_from_db()
    operation.refresh_from_db()
    assert holder["provider"].get_instance_calls[-1].resource_id == node.external_id
    assert node.raw_cloud_state == "running"
    assert node.addresses == [
        {
            "value": "198.51.100.20",
            "family": 4,
            "kind": "dynamic",
            "resource_id": node.external_id,
        }
    ]
    assert node.observed_at is not None
    assert node.observation_error == ""
    assert refresh == [node.pk]
    assert operation.status == "SUCCEEDED"
    assert operation.result["addresses_changed"] is True


@pytest.mark.django_db
def test_reboot_waits_for_cloud_operation_before_persisting_replacement_ip(
    prepared_node, admin, monkeypatch
):
    from providers.base import Address

    node, _create_operation = prepared_node
    provision_node_for_action(node)
    operation = make_node_action(admin, node, "reboot")
    lifecycle, holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        },
    )
    provider.addresses_after_lifecycle_write = (
        Address("198.51.100.23", 4, "dynamic", node.external_id),
    )
    provider.defer_reboot_address_until_operation_complete = True
    provider.reboot_operation_statuses = ["IN_PROGRESS", "SUCCEEDED"]
    monkeypatch.setattr("apps.nodes.lifecycle.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "apps.subscriptions.publishing.Publisher.refresh_node_address",
        lambda _node_id: {"published": 1, "failed": 0},
    )

    lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)

    node.refresh_from_db()
    operation.refresh_from_db()
    write_step = operation.steps.get(name="cloud.reboot")
    assert write_step.evidence["provider_operation_id"] == "fake-reboot-operation"
    assert provider.reboot_operation_status_calls == [
        "fake-reboot-operation",
        "fake-reboot-operation",
    ]
    assert holder["provider"].action_calls == ["reboot"]
    assert node.addresses[0]["value"] == "198.51.100.23"
    assert operation.status == "SUCCEEDED"
    assert operation.result["provider_operation_status"] == "SUCCEEDED"


@pytest.mark.django_db
def test_reboot_timeout_retries_same_operation_without_rebooting_again(
    prepared_node, admin, monkeypatch
):
    from apps.operations.services import OperationService
    from providers.base import Address

    node, _create_operation = prepared_node
    provision_node_for_action(node)
    operation = make_node_action(admin, node, "reboot")
    lifecycle, holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        },
    )
    provider.addresses_after_lifecycle_write = (
        Address("198.51.100.24", 4, "dynamic", node.external_id),
    )
    provider.defer_reboot_address_until_operation_complete = True
    provider.reboot_operation_statuses = ["IN_PROGRESS"]
    monkeypatch.setattr("apps.nodes.lifecycle.PROVIDER_OPERATION_TIMEOUT_SECONDS", 0)

    lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)

    node.refresh_from_db()
    operation.refresh_from_db()
    assert node.addresses[0]["value"] == "192.0.2.10"
    assert operation.status == "NEEDS_RECONCILIATION"
    assert operation.error_code == "CLOUD_OPERATION_PENDING"

    OperationService.retry(operation.pk, admin=admin)
    provider.reboot_operation_statuses = ["IN_PROGRESS", "SUCCEEDED"]
    monkeypatch.setattr("apps.nodes.lifecycle.PROVIDER_OPERATION_TIMEOUT_SECONDS", 10)
    monkeypatch.setattr("apps.nodes.lifecycle.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "apps.subscriptions.publishing.Publisher.refresh_node_address",
        lambda _node_id: {"published": 1, "failed": 0},
    )
    lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)

    node.refresh_from_db()
    operation.refresh_from_db()
    assert holder["provider"].action_calls == ["reboot"]
    assert node.addresses[0]["value"] == "198.51.100.24"
    assert operation.status == "SUCCEEDED"


@pytest.mark.django_db
def test_unconfirmed_reboot_does_not_write_addresses_or_publish_subscriptions(
    prepared_node, admin, monkeypatch
):
    from providers.base import Address

    node, _create_operation = prepared_node
    provision_node_for_action(node)
    operation = make_node_action(admin, node, "reboot")
    lifecycle, holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        },
    )
    provider.addresses_after_lifecycle_write = (
        Address("198.51.100.25", 4, "dynamic", node.external_id),
    )
    provider.defer_reboot_address_until_operation_complete = True
    provider.reboot_operation_statuses = ["IN_PROGRESS"]
    monkeypatch.setattr("apps.nodes.lifecycle.PROVIDER_OPERATION_TIMEOUT_SECONDS", 0)
    refresh = []
    monkeypatch.setattr(
        "apps.subscriptions.publishing.Publisher.refresh_node_address",
        lambda node_id: refresh.append(node_id) or {"published": 1, "failed": 0},
    )

    lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)

    node.refresh_from_db()
    operation.refresh_from_db()
    assert node.addresses[0]["value"] == "192.0.2.10"
    assert refresh == []
    assert holder["provider"].action_calls == ["reboot"]
    assert operation.status == "NEEDS_RECONCILIATION"
    assert operation.error_code == "CLOUD_OPERATION_PENDING"


@pytest.mark.django_db
def test_start_waits_for_delayed_ipv4_and_stable_readback(
    prepared_node, admin, monkeypatch
):
    from providers.base import Address

    node, _create_operation = prepared_node
    provision_node_for_action(node)
    operation = make_node_action(admin, node, "start")
    lifecycle, holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        },
        state="stopped",
    )
    provider.addresses_after_lifecycle_write = (
        Address("198.51.100.26", 4, "dynamic", node.external_id),
    )
    provider.defer_start_address_until_operation_complete = True
    provider.lifecycle_readback_addresses = [
        (Address("192.0.2.10", 4, "dynamic", node.external_id),),
        (Address("198.51.100.26", 4, "dynamic", node.external_id),),
        (Address("198.51.100.26", 4, "dynamic", node.external_id),),
    ]
    monkeypatch.setattr("apps.nodes.lifecycle.time.sleep", lambda _seconds: None)
    refresh = []
    monkeypatch.setattr(
        "apps.subscriptions.publishing.Publisher.refresh_node_address",
        lambda node_id: refresh.append(node_id) or {"published": 1, "failed": 0},
    )

    lifecycle.dispatch("start", node.pk, operation_id=operation.pk)

    node.refresh_from_db()
    operation.refresh_from_db()
    assert holder["provider"].action_calls == ["start"]
    assert provider.start_operation_status_calls == ["fake-start-operation"]
    assert node.addresses[0]["value"] == "198.51.100.26"
    assert refresh == [node.pk]
    assert operation.status == "SUCCEEDED"
    assert operation.result["addresses_changed"] is True
    assert operation.steps.filter(
        name="cloud.start.read_after_write",
        evidence__address_stabilized=True,
    ).exists()


@pytest.mark.django_db
def test_start_address_propagation_timeout_keeps_old_ip_and_retries_read_only(
    prepared_node, admin, monkeypatch
):
    from apps.operations.services import OperationService
    from providers.base import Address

    node, _create_operation = prepared_node
    provision_node_for_action(node)
    operation = make_node_action(admin, node, "start")
    lifecycle, holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        },
        state="stopped",
    )
    provider.addresses_after_lifecycle_write = (
        Address("198.51.100.27", 4, "dynamic", node.external_id),
    )
    provider.defer_start_address_until_operation_complete = True
    provider.lifecycle_readback_addresses = [
        (Address("192.0.2.10", 4, "dynamic", node.external_id),),
    ]
    monkeypatch.setattr("apps.nodes.lifecycle.INSTANCE_READBACK_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr("apps.nodes.lifecycle.time.sleep", lambda _seconds: None)

    lifecycle.dispatch("start", node.pk, operation_id=operation.pk)

    node.refresh_from_db()
    operation.refresh_from_db()
    assert node.addresses[0]["value"] == "192.0.2.10"
    assert operation.status == "NEEDS_RECONCILIATION"
    assert operation.error_code == "CLOUD_ADDRESS_PROPAGATION_PENDING"

    OperationService.retry(operation.pk, admin=admin)
    provider.defer_start_address_until_operation_complete = False
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        },
        state="running",
        addresses=provider.addresses_after_lifecycle_write,
    )
    monkeypatch.setattr("apps.nodes.lifecycle.INSTANCE_READBACK_TIMEOUT_SECONDS", 10)
    lifecycle.dispatch("start", node.pk, operation_id=operation.pk)

    operation.refresh_from_db()
    node.refresh_from_db()
    assert holder["provider"].action_calls == ["start"]
    assert node.addresses[0]["value"] == "198.51.100.27"
    assert operation.status == "SUCCEEDED"
    assert operation.result["reconciled"] is True


@pytest.mark.django_db
def test_start_readback_failure_keeps_old_cloud_snapshot_and_requires_reconciliation(
    prepared_node, admin, monkeypatch
):
    node, _create_operation = prepared_node
    provision_node_for_action(node)
    previous_observed_at = node.observed_at
    operation = make_node_action(admin, node, "start")
    lifecycle, _holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        },
        state="stopped",
    )
    provider.fail_lifecycle_readback_after_write = True
    monkeypatch.setattr("apps.nodes.lifecycle.INSTANCE_READBACK_TIMEOUT_SECONDS", 0)

    lifecycle.dispatch("start", node.pk, operation_id=operation.pk)

    node.refresh_from_db()
    operation.refresh_from_db()
    assert node.raw_cloud_state == "stopped"
    assert node.addresses[0]["value"] == "192.0.2.10"
    assert node.observed_at == previous_observed_at
    assert node.observation_error == "CLOUD_READ_AFTER_WRITE_UNCONFIRMED"
    assert operation.status == "NEEDS_RECONCILIATION"
    assert operation.error_code == "CLOUD_READ_AFTER_WRITE_UNCONFIRMED"


@pytest.mark.django_db
def test_reboot_with_wrong_owner_readback_does_not_write_address(prepared_node, admin):
    node, _create_operation = prepared_node
    provision_node_for_action(node)
    operation = make_node_action(admin, node, "reboot")
    lifecycle, _holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": "another-node-operation",
        },
        state="stopped",
    )

    lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)

    node.refresh_from_db()
    operation.refresh_from_db()
    assert node.addresses[0]["value"] == "192.0.2.10"
    assert node.raw_cloud_state == "stopped"
    assert node.observation_error == "RESOURCE_OWNERSHIP_MISMATCH"
    assert operation.status == "NEEDS_RECONCILIATION"
    assert operation.error_code == "CLOUD_READ_AFTER_WRITE_TARGET_MISMATCH"


@pytest.mark.django_db
def test_unknown_reboot_write_does_not_publish_unconfirmed_address(
    prepared_node, admin, monkeypatch
):
    from providers.base import Address

    node, _create_operation = prepared_node
    provision_node_for_action(node)
    operation = make_node_action(admin, node, "reboot")
    lifecycle, _holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        },
        state="stopped",
    )
    provider.addresses_after_lifecycle_write = (
        Address("198.51.100.21", 4, "dynamic", node.external_id),
    )
    provider.lifecycle_write_unknown = True
    refresh = []
    monkeypatch.setattr(
        "apps.subscriptions.publishing.Publisher.refresh_node_address",
        lambda node_id: refresh.append(node_id) or {"published": 0, "failed": 0},
    )

    lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)

    node.refresh_from_db()
    operation.refresh_from_db()
    assert node.addresses[0]["value"] == "192.0.2.10"
    assert refresh == []
    assert operation.status == "NEEDS_RECONCILIATION"
    assert operation.error_code == "CLOUD_OPERATION_ID_MISSING"


@pytest.mark.django_db
def test_retry_of_unknown_reboot_is_read_only(prepared_node, admin):
    from apps.operations.services import OperationService

    node, _create_operation = prepared_node
    provision_node_for_action(node)
    operation = make_node_action(admin, node, "reboot")
    lifecycle, holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        },
        state="stopped",
    )
    provider.lifecycle_write_unknown = True

    lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)
    OperationService.retry(operation.pk, admin=admin)
    lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)

    operation.refresh_from_db()
    assert holder["provider"].action_calls == ["reboot"]
    assert operation.status == "NEEDS_RECONCILIATION"
    assert operation.error_code == "CLOUD_OPERATION_ID_MISSING"


@pytest.mark.django_db
def test_reboot_crash_after_acceptance_does_not_adopt_snapshot_diff_candidate(
    prepared_node, admin, monkeypatch
):
    from datetime import timedelta

    from django.utils import timezone
    from providers.base import Address

    class SimulatedProcessCrash(BaseException):
        pass

    node, _create_operation = prepared_node
    provision_node_for_action(node)
    operation = make_node_action(admin, node, "reboot")
    lifecycle, holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        },
        state="stopped",
    )
    provider.addresses_after_lifecycle_write = (
        Address("198.51.100.29", 4, "dynamic", node.external_id),
    )
    provider.omit_lifecycle_operation_id = True
    original_reboot = provider.reboot_instance

    def crash_after_acceptance(resource, *, permit):
        original_reboot(resource, permit=permit)
        raise SimulatedProcessCrash()

    monkeypatch.setattr(provider, "reboot_instance", crash_after_acceptance)
    with pytest.raises(SimulatedProcessCrash):
        lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)

    intent = operation.steps.get(name="cloud.reboot")
    assert intent.status == "WRITE_INTENT"
    assert intent.finished_at is None
    assert intent.evidence["provider_operation_ids_before_write"] == []
    assert holder["provider"].action_calls == ["reboot"]

    operation.lease_expires_at = timezone.now() - timedelta(seconds=1)
    operation.save(update_fields=["lease_expires_at", "updated_at"])
    monkeypatch.setattr(provider, "reboot_instance", original_reboot)
    monkeypatch.setattr(
        "apps.subscriptions.publishing.Publisher.refresh_node_address",
        lambda _node_id: {"published": 1, "failed": 0},
    )
    lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)

    operation.refresh_from_db()
    node.refresh_from_db()
    intent.refresh_from_db()
    assert holder["provider"].action_calls == ["reboot"]
    assert "provider_operation_id" not in intent.evidence
    assert provider.reboot_operation_status_calls == []
    assert node.addresses[0]["value"] == "192.0.2.10"
    assert operation.status == "NEEDS_RECONCILIATION"
    assert operation.error_code == "CLOUD_OPERATION_ID_UNOWNED"


@pytest.mark.django_db
def test_reboot_retry_rejects_multiple_new_operations_without_another_write(
    prepared_node, admin, monkeypatch
):
    from datetime import timedelta

    from django.utils import timezone

    class SimulatedProcessCrash(BaseException):
        pass

    node, _create_operation = prepared_node
    provision_node_for_action(node)
    operation = make_node_action(admin, node, "reboot")
    lifecycle, holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        },
        state="stopped",
    )
    original_reboot = provider.reboot_instance

    def crash_after_acceptance(resource, *, permit):
        original_reboot(resource, permit=permit)
        raise SimulatedProcessCrash()

    monkeypatch.setattr(provider, "reboot_instance", crash_after_acceptance)
    with pytest.raises(SimulatedProcessCrash):
        lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)

    provider.lifecycle_operation_ids["reboot"].append("other-operator-operation")
    operation.lease_expires_at = timezone.now() - timedelta(seconds=1)
    operation.save(update_fields=["lease_expires_at", "updated_at"])
    monkeypatch.setattr(provider, "reboot_instance", original_reboot)
    lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)

    operation.refresh_from_db()
    assert holder["provider"].action_calls == ["reboot"]
    assert operation.status == "NEEDS_RECONCILIATION"
    assert operation.error_code == "CLOUD_OPERATION_LOOKUP_AMBIGUOUS"


@pytest.mark.django_db
def test_reboot_retry_does_not_adopt_single_external_operation_after_snapshot(
    prepared_node, admin, monkeypatch
):
    from datetime import timedelta

    from apps.operations.services import OperationService
    from django.utils import timezone

    class SimulatedProcessCrash(BaseException):
        pass

    node, _create_operation = prepared_node
    provision_node_for_action(node)
    operation = make_node_action(admin, node, "reboot")
    lifecycle, holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        },
        state="stopped",
    )

    def crash_before_write(_resource, *, permit):
        raise SimulatedProcessCrash()

    monkeypatch.setattr(provider, "reboot_instance", crash_before_write)
    with pytest.raises(SimulatedProcessCrash):
        lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)

    intent = operation.steps.get(name="cloud.reboot")
    assert intent.evidence["provider_operation_ids_before_write"] == []
    provider.lifecycle_operation_ids["reboot"].append("other-operator-operation")
    operation.lease_expires_at = timezone.now() - timedelta(seconds=1)
    operation.save(update_fields=["lease_expires_at", "updated_at"])

    def forbidden_retry_write(_resource, *, permit):
        raise SimulatedProcessCrash()

    monkeypatch.setattr(provider, "reboot_instance", forbidden_retry_write)
    refresh = []
    monkeypatch.setattr(
        "apps.subscriptions.publishing.Publisher.refresh_node_address",
        lambda node_id: refresh.append(node_id) or {"published": 1, "failed": 0},
    )

    lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)
    operation.refresh_from_db()
    node.refresh_from_db()
    assert holder["provider"].action_calls == []
    assert provider.reboot_operation_status_calls == []
    assert node.addresses[0]["value"] == "192.0.2.10"
    assert refresh == []
    assert operation.status == "NEEDS_RECONCILIATION"
    assert operation.error_code == "CLOUD_OPERATION_ID_UNOWNED"

    OperationService.retry(operation.pk, admin=admin)
    lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)
    operation.refresh_from_db()
    assert holder["provider"].action_calls == []
    assert operation.status == "NEEDS_RECONCILIATION"
    assert operation.error_code == "CLOUD_OPERATION_ID_UNOWNED"


@pytest.mark.django_db
def test_missing_reboot_operation_id_is_queried_again_without_rebooting(
    prepared_node, admin, monkeypatch
):
    from apps.operations.services import OperationService
    from providers.base import Address

    node, _create_operation = prepared_node
    provision_node_for_action(node)
    operation = make_node_action(admin, node, "reboot")
    lifecycle, holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        },
    )
    provider.omit_lifecycle_operation_id = True
    provider.addresses_after_lifecycle_write = (
        Address("198.51.100.28", 4, "dynamic", node.external_id),
    )
    provider.defer_reboot_address_until_operation_complete = True
    monkeypatch.setattr("apps.nodes.lifecycle.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "apps.subscriptions.publishing.Publisher.refresh_node_address",
        lambda _node_id: {"published": 1, "failed": 0},
    )

    lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)

    node.refresh_from_db()
    operation.refresh_from_db()
    assert node.addresses[0]["value"] == "192.0.2.10"
    assert operation.status == "NEEDS_RECONCILIATION"
    assert operation.error_code == "CLOUD_OPERATION_ID_UNOWNED"

    OperationService.retry(operation.pk, admin=admin)
    lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)

    node.refresh_from_db()
    operation.refresh_from_db()
    assert holder["provider"].action_calls == ["reboot"]
    assert len(provider.lifecycle_operation_snapshot_calls) == 3
    assert provider.reboot_operation_status_calls == []
    assert node.addresses[0]["value"] == "192.0.2.10"
    assert operation.error_code == "CLOUD_OPERATION_ID_UNOWNED"
    assert operation.status == "NEEDS_RECONCILIATION"


@pytest.mark.django_db
def test_reboot_without_ipv4_does_not_clear_saved_address_or_publish(
    prepared_node, admin, monkeypatch
):
    from providers.base import Address

    node, _create_operation = prepared_node
    provision_node_for_action(node)
    operation = make_node_action(admin, node, "reboot")
    lifecycle, _holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        },
        addresses=(),
    )
    provider.addresses_after_lifecycle_write = ()
    provider.reboot_operation_statuses = ["SUCCEEDED"]
    monkeypatch.setattr("apps.nodes.lifecycle.INSTANCE_READBACK_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr("apps.nodes.lifecycle.time.sleep", lambda _seconds: None)
    refresh = []
    monkeypatch.setattr(
        "apps.subscriptions.publishing.Publisher.refresh_node_address",
        lambda node_id: refresh.append(node_id) or {"published": 1, "failed": 0},
    )

    lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)

    node.refresh_from_db()
    operation.refresh_from_db()
    assert node.addresses[0]["value"] == "192.0.2.10"
    assert refresh == []
    assert operation.status == "NEEDS_RECONCILIATION"
    assert operation.error_code == "CLOUD_IPV4_READBACK_UNAVAILABLE"


@pytest.mark.django_db
def test_retry_republishes_new_address_without_rebooting_again(
    prepared_node, admin, monkeypatch
):
    from apps.operations.services import OperationService
    from providers.base import Address

    node, _create_operation = prepared_node
    provision_node_for_action(node)
    operation = make_node_action(admin, node, "reboot")
    lifecycle, holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        },
        state="stopped",
    )
    provider.addresses_after_lifecycle_write = (
        Address("198.51.100.22", 4, "dynamic", node.external_id),
    )
    publication_results = iter(
        ({"published": 0, "failed": 1}, {"published": 1, "failed": 0})
    )
    monkeypatch.setattr(
        "apps.subscriptions.publishing.Publisher.refresh_node_address",
        lambda _node_id: next(publication_results),
    )

    lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)
    operation.refresh_from_db()
    assert operation.status == "NEEDS_RECONCILIATION"
    OperationService.retry(operation.pk, admin=admin)
    lifecycle.dispatch("reboot", node.pk, operation_id=operation.pk)

    operation.refresh_from_db()
    node.refresh_from_db()
    assert holder["provider"].action_calls == ["reboot"]
    assert node.addresses[0]["value"] == "198.51.100.22"
    assert operation.status == "SUCCEEDED"
    assert operation.result["reconciled"] is True


@pytest.mark.django_db
def test_delete_releases_quota_only_after_exact_absence_readback(prepared_node, admin):
    from apps.nodes.models import ManagedNode

    node, _create_operation = prepared_node
    provision_node_for_delete(node)
    operation = make_delete_operation(admin, node)
    lifecycle, holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(operation.idempotency_key),
        },
    )

    lifecycle.dispatch("delete", node.pk, operation_id=operation.pk)

    node = ManagedNode.objects.get(pk=node.pk)
    operation.refresh_from_db()
    assert holder["provider"].deleted is True
    assert node.consumes_quota is False
    assert node.desired_state == "DELETED"
    assert node.provisioning_state == "DELETED"
    assert operation.status == "SUCCEEDED"
    assert operation.result["cloud_absence_confirmed"] is True
    assert operation.result["quota_released"] is True
    assert operation.steps.filter(
        name="cloud.delete.read_after_write", status="CONFIRMED_ABSENT"
    ).exists()


@pytest.mark.django_db
def test_delete_keeps_quota_when_readback_finds_resource(prepared_node, admin):
    from apps.nodes.models import ManagedNode

    node, _create_operation = prepared_node
    provision_node_for_delete(node)
    operation = make_delete_operation(admin, node)
    lifecycle, holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.retain_after_delete = True
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(operation.idempotency_key),
        },
    )

    lifecycle.dispatch("delete", node.pk, operation_id=operation.pk)

    node = ManagedNode.objects.get(pk=node.pk)
    operation.refresh_from_db()
    assert node.consumes_quota is True
    assert node.desired_state == "PRESENT"
    assert operation.status == "NEEDS_RECONCILIATION"
    assert operation.error_code == "CLOUD_DELETE_READ_AFTER_WRITE_UNCONFIRMED"
    assert operation.steps.filter(
        name="cloud.delete.read_after_write", status="RESOURCE_PRESENT"
    ).exists()


@pytest.mark.django_db
def test_delete_keeps_quota_when_readback_is_unavailable(prepared_node, admin):
    from apps.nodes.models import ManagedNode

    node, _create_operation = prepared_node
    provision_node_for_delete(node)
    operation = make_delete_operation(admin, node)
    lifecycle, holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.fail_delete_readback = True
    provider.instances[node.external_id] = provider._instance(
        node.external_id,
        {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(operation.idempotency_key),
        },
    )

    lifecycle.dispatch("delete", node.pk, operation_id=operation.pk)

    node = ManagedNode.objects.get(pk=node.pk)
    operation.refresh_from_db()
    assert holder["provider"].deleted is True
    assert node.consumes_quota is True
    assert node.desired_state == "PRESENT"
    assert operation.status == "NEEDS_RECONCILIATION"
    assert operation.error_code == "CLOUD_DELETE_READ_AFTER_WRITE_UNCONFIRMED"
    assert operation.error_details == {"read_error_code": "CLOUD_READ_FAILED"}


@pytest.mark.django_db
@pytest.mark.parametrize("provider", ["aws_lightsail", "aliyun_swas"])
def test_both_provider_kinds_use_same_lifecycle_contract(
    admin, cloud_account, provider
):
    from apps.nodes.models import NodePool
    from apps.nodes.quota import reserve_node
    from apps.operations.services import OperationService

    cloud_account.provider = provider
    cloud_account.external_account_id = f"fake-{provider}"
    cloud_account.save(update_fields=["provider", "external_account_id", "updated_at"])
    pool = NodePool.objects.create(name=f"pool-{provider}", region="test-region", quota=1)
    key = uuid4()
    node = reserve_node(
        pool.pk,
        account_id=cloud_account.pk,
        region="test-region",
        plan_id="small",
        image_id="debian-12",
        operation_key=key,
    )
    operation = OperationService.submit(
        kind="node.create",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(cloud_account.pk)},
        key=key,
        preview_id=None,
        admin=admin,
        cloud_credential_version=node.cloud_credential_version,
    )
    lifecycle, _holder = make_lifecycle(node)
    lifecycle.create(node.pk, operation_id=operation.pk)
    node.refresh_from_db()
    assert node.provisioning_state == "PROVISIONED"
