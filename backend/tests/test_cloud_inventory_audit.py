from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from providers.base import AccountIdentity, AccountRef, Instance, Region, ResourceRef


class FakeInventoryReader:
    def __init__(self, account, region, instances_by_region, *, fail_regions=()):
        self.account = account
        self.region = region
        self.instances_by_region = instances_by_region
        self.fail_regions = set(fail_regions)

    def validate_credentials(self):
        return AccountIdentity(
            self.account.provider,
            self.account.external_account_id,
            "fake-principal",
            datetime.now(UTC),
        )

    def list_regions(self):
        return tuple(
            Region(region, region)
            for region in ("us-east-1", "us-west-2")
            if region in self.instances_by_region
        )

    def list_instances(self, region):
        if region in self.fail_regions:
            from common.errors import DomainError

            raise DomainError("AWS_ACCESS_DENIED", "redacted", status_code=403)
        return self.instances_by_region.get(region, ())


def cloud_instance(account, region, external_id):
    return Instance(
        ref=ResourceRef(
            account=AccountRef(
                account.pk,
                account.provider,
                account.external_account_id,
                account.credential_version,
            ),
            region=region,
            resource_id=external_id,
        ),
        name=external_id,
        state="running",
        raw_state="running",
        addresses=(),
        tags={},
        observed_at=datetime.now(UTC),
    )


def track_instance(node, external_id):
    from apps.nodes.models import NodeResource

    return NodeResource.objects.create(
        node=node,
        kind="instance",
        external_id=external_id,
        cost_status="ACTIVE",
    )


@pytest.mark.django_db
def test_inventory_audit_reports_untracked_and_missing_without_mutation(
    cloud_account, prepared_node, monkeypatch
):
    from apps.nodes.inventory import reconcile_cloud_account_inventory
    from apps.nodes.models import ManagedNode

    node, _ = prepared_node
    node.external_id = "managed-1"
    node.save(update_fields=["external_id", "updated_at"])
    track_instance(node, "managed-1")
    regions = {
        "us-east-1": (
            cloud_instance(cloud_account, "us-east-1", "managed-1"),
            cloud_instance(cloud_account, "us-east-1", "manual-1"),
        )
    }
    monkeypatch.setattr(
        "apps.nodes.inventory.build_read_provider",
        lambda account_id, region, credential_version=None: FakeInventoryReader(
            cloud_account, region, regions
        ),
    )

    result = reconcile_cloud_account_inventory(cloud_account)

    assert result["complete"] is True
    assert result["cloud_instance_count"] == 2
    assert result["managed_node_count"] == 1
    assert result["untracked_cloud_instances"] == [
        {"region": "us-east-1", "external_id": "manual-1"}
    ]
    assert result["missing_managed_instances"] == []
    assert ManagedNode.objects.get(pk=node.pk).external_id == "managed-1"


@pytest.mark.django_db
def test_inventory_audit_marks_missing_managed_id_and_pending_node(
    cloud_account, prepared_node, monkeypatch
):
    from apps.nodes.inventory import reconcile_cloud_account_inventory

    node, _ = prepared_node
    node.external_id = "managed-1"
    node.save(update_fields=["external_id", "updated_at"])
    track_instance(node, "managed-1")
    regions = {"us-east-1": ()}
    monkeypatch.setattr(
        "apps.nodes.inventory.build_read_provider",
        lambda account_id, region, credential_version=None: FakeInventoryReader(
            cloud_account, region, regions
        ),
    )

    result = reconcile_cloud_account_inventory(cloud_account)

    assert result["complete"] is True
    assert result["missing_managed_instances"] == [
        {"region": "us-east-1", "external_id": "managed-1"}
    ]


@pytest.mark.django_db
def test_failed_region_never_produces_a_complete_zero_or_orphan_claim(
    cloud_account, prepared_node, monkeypatch
):
    from apps.nodes.inventory import reconcile_cloud_account_inventory

    node, _ = prepared_node
    node.region = "us-west-2"
    node.external_id = "managed-west"
    node.save(update_fields=["region", "external_id", "updated_at"])
    track_instance(node, "managed-west")
    regions = {"us-east-1": (), "us-west-2": ()}
    monkeypatch.setattr(
        "apps.nodes.inventory.build_read_provider",
        lambda account_id, region, credential_version=None: FakeInventoryReader(
            cloud_account, region, regions, fail_regions={"us-west-2"}
        ),
    )

    result = reconcile_cloud_account_inventory(cloud_account)

    assert result["complete"] is False
    assert result["failed_regions"] == [{"region": "us-west-2", "error_code": "AWS_ACCESS_DENIED"}]
    assert result["missing_managed_instances"] == []
    assert "us-west-2" not in result["complete_regions"]


@pytest.mark.django_db
def test_inventory_audit_rejects_cloud_identity_mismatch_before_region_scan(
    cloud_account, monkeypatch
):
    from apps.nodes.inventory import reconcile_cloud_account_inventory
    from common.errors import DomainError

    class WrongIdentity(FakeInventoryReader):
        def validate_credentials(self):
            return AccountIdentity(
                self.account.provider,
                "999999999999",
                "wrong-principal",
                datetime.now(UTC),
            )

    reader = WrongIdentity(cloud_account, "us-east-1", {})
    monkeypatch.setattr(
        "apps.nodes.inventory.build_read_provider",
        lambda account_id, region, credential_version=None: reader,
    )

    with pytest.raises(DomainError) as caught:
        reconcile_cloud_account_inventory(cloud_account)

    assert caught.value.code == "CLOUD_IDENTITY_MISMATCH"


@pytest.mark.django_db
def test_inventory_audit_rejects_empty_provider_region_catalog(cloud_account, monkeypatch):
    from apps.nodes.inventory import reconcile_cloud_account_inventory
    from common.errors import DomainError

    class NoRegions(FakeInventoryReader):
        def list_regions(self):
            return ()

    monkeypatch.setattr(
        "apps.nodes.inventory.build_read_provider",
        lambda account_id, region, credential_version=None: NoRegions(
            cloud_account, region, {}
        ),
    )

    with pytest.raises(DomainError) as caught:
        reconcile_cloud_account_inventory(cloud_account)

    assert caught.value.code == "CLOUD_INVENTORY_REGIONS_UNAVAILABLE"


@pytest.mark.django_db
def test_inventory_scans_pending_node_region_even_when_provider_has_no_regions(
    cloud_account, prepared_node, monkeypatch
):
    from apps.nodes.inventory import reconcile_cloud_account_inventory

    node, _ = prepared_node
    node.region = "eu-west-1"
    node.external_id = ""
    node.save(update_fields=["region", "external_id", "updated_at"])
    track_instance(node, "pending-tagged")
    reader = FakeInventoryReader(cloud_account, "eu-west-1", {"us-east-1": ()})
    monkeypatch.setattr(
        "apps.nodes.inventory.build_read_provider",
        lambda account_id, region, credential_version=None: reader,
    )

    result = reconcile_cloud_account_inventory(cloud_account)

    assert result["checked_regions"] == ["eu-west-1", "us-east-1"]
    assert result["pending_managed_node_count"] == 1
    assert result["complete"] is True
    assert result["node_count_reconciled"] is False


@pytest.mark.django_db
def test_inventory_count_does_not_hide_duplicate_managed_instance_ids(
    cloud_account, prepared_node, monkeypatch
):
    from uuid import uuid4

    from apps.nodes.inventory import reconcile_cloud_account_inventory
    from apps.nodes.quota import reserve_node

    node, _ = prepared_node
    node.external_id = "managed-1"
    node.save(update_fields=["external_id", "updated_at"])
    track_instance(node, "managed-1")
    duplicate = reserve_node(
        node.pool_id,
        account_id=cloud_account.pk,
        region=node.region,
        plan_id=node.plan_id,
        image_id=node.image_id,
        operation_key=uuid4(),
    )
    duplicate.external_id = "managed-1"
    duplicate.save(update_fields=["external_id", "updated_at"])
    track_instance(duplicate, "managed-1")
    regions = {"us-east-1": (cloud_instance(cloud_account, "us-east-1", "managed-1"),)}
    monkeypatch.setattr(
        "apps.nodes.inventory.build_read_provider",
        lambda account_id, region, credential_version=None: FakeInventoryReader(
            cloud_account, region, regions
        ),
    )

    result = reconcile_cloud_account_inventory(cloud_account)

    assert result["managed_node_count"] == 2
    assert result["tracked_cloud_instance_count"] == 2
    assert result["cloud_instance_count"] == 1
    assert result["node_count_reconciled"] is False
    assert result["resource_binding_error_count"] == 1


@pytest.mark.django_db
def test_inventory_allows_the_same_instance_id_in_different_regions(
    cloud_account, prepared_node, monkeypatch
):
    from uuid import uuid4

    from apps.nodes.inventory import reconcile_cloud_account_inventory
    from apps.nodes.models import NodePoolRegionAllocation
    from apps.nodes.quota import reserve_node

    first, _ = prepared_node
    NodePoolRegionAllocation.objects.create(
        pool=first.pool, region="us-west-2", quota=1
    )
    first.external_id = "reused-regional-id"
    first.save(update_fields=["external_id", "updated_at"])
    track_instance(first, "reused-regional-id")
    second = reserve_node(
        first.pool_id,
        account_id=cloud_account.pk,
        region="us-west-2",
        plan_id=first.plan_id,
        image_id=first.image_id,
        operation_key=uuid4(),
    )
    second.external_id = "reused-regional-id"
    second.save(update_fields=["external_id", "updated_at"])
    track_instance(second, "reused-regional-id")
    regions = {
        "us-east-1": (
            cloud_instance(cloud_account, "us-east-1", "reused-regional-id"),
        ),
        "us-west-2": (
            cloud_instance(cloud_account, "us-west-2", "reused-regional-id"),
        ),
    }
    monkeypatch.setattr(
        "apps.nodes.inventory.build_read_provider",
        lambda account_id, region, credential_version=None: FakeInventoryReader(
            cloud_account, region, regions
        ),
    )

    result = reconcile_cloud_account_inventory(cloud_account)

    assert result["complete"] is True
    assert result["resource_binding_error_count"] == 0
    assert result["cloud_instance_count"] == 2
    assert result["node_count_reconciled"] is True


@pytest.mark.django_db
def test_inventory_audit_task_skips_cloud_calls_when_network_gate_is_closed(
    cloud_account, monkeypatch
):
    from apps.audit.models import AuditEvent
    from apps.nodes.tasks import audit_cloud_instance_inventory

    monkeypatch.setattr(
        "apps.identity.gate_settings.provider_identity_network_setting",
        lambda: {"enabled": False, "source": "DATABASE"},
    )
    reconcile = Mock(side_effect=AssertionError("provider call must be gated"))
    monkeypatch.setattr("apps.nodes.inventory.reconcile_cloud_account_inventory", reconcile)

    result = audit_cloud_instance_inventory()

    assert result == {"audited": 0, "blocked": 0, "disabled": True}
    reconcile.assert_not_called()
    assert AuditEvent.objects.count() == 0


@pytest.mark.django_db
def test_inventory_audit_task_records_sanitized_partial_event_and_continues(
    cloud_account, monkeypatch
):
    from apps.audit.models import AuditEvent
    from apps.nodes.tasks import audit_cloud_instance_inventory

    second = type(cloud_account).objects.create(
        name="Second Fake AWS",
        provider="aws_lightsail",
        external_account_id="987654321012",
        credential_version=1,
        enabled=True,
    )
    third = type(cloud_account).objects.create(
        name="Third Fake AWS",
        provider="aws_lightsail",
        external_account_id="111222333444",
        credential_version=1,
        enabled=True,
    )
    monkeypatch.setattr(
        "apps.identity.gate_settings.provider_identity_network_setting",
        lambda: {"enabled": True, "source": "DATABASE"},
    )

    def reconcile(account):
        if account.pk == cloud_account.pk:
            return {
                "account_id": str(account.pk),
                "complete": True,
                "node_count_reconciled": True,
                "untracked_cloud_instances": [],
            }
        if account.pk == second.pk:
            from common.errors import DomainError

            raise DomainError("CLOUD_IDENTITY_MISMATCH", "sensitive provider response marker")
        raise RuntimeError("sensitive provider response marker")

    monkeypatch.setattr("apps.nodes.inventory.reconcile_cloud_account_inventory", reconcile)

    result = audit_cloud_instance_inventory()

    assert result == {"audited": 3, "blocked": 2, "disabled": False}
    events = {event.target_id: event for event in AuditEvent.objects.all()}
    assert events[str(cloud_account.pk)].result == "SUCCEEDED"
    assert events[str(second.pk)].result == "PARTIAL"
    assert events[str(second.pk)].metadata["error_code"] == "CLOUD_IDENTITY_MISMATCH"
    assert "sensitive provider response marker" not in str(events[str(second.pk)].metadata)
    assert events[str(third.pk)].result == "PARTIAL"
    assert events[str(third.pk)].metadata["error_code"] == "CLOUD_INVENTORY_READ_FAILED"
    assert "sensitive provider response marker" not in str(events[str(third.pk)].metadata)


@pytest.mark.django_db
def test_inventory_audit_task_ignores_disabled_accounts(cloud_account, monkeypatch):
    from apps.audit.models import AuditEvent
    from apps.nodes.tasks import audit_cloud_instance_inventory

    cloud_account.enabled = False
    cloud_account.save(update_fields=["enabled", "updated_at"])
    monkeypatch.setattr(
        "apps.identity.gate_settings.provider_identity_network_setting",
        lambda: {"enabled": True, "source": "DATABASE"},
    )
    reconcile = Mock()
    monkeypatch.setattr("apps.nodes.inventory.reconcile_cloud_account_inventory", reconcile)

    result = audit_cloud_instance_inventory()

    assert result == {"audited": 0, "blocked": 0, "disabled": False}
    reconcile.assert_not_called()
    assert AuditEvent.objects.count() == 0
