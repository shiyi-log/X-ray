from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import NodeAutomationSetting
from apps.nodes.models import ManagedNode, NodePool, NodePoolRegionAllocation, NodeResource
from apps.nodes.quota import set_allocations
from apps.operations.models import Operation
from common.errors import DomainError


@pytest.fixture
def system_client(admin, settings):
    settings.XRAY_ENV = "test"
    settings.XRAY_LOCAL_ONE_CLICK_LOGIN = True
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auth/csrf", HTTP_HOST="127.0.0.1")
    client.credentials(HTTP_X_CSRFTOKEN=csrf.json()["csrf_token"])
    assert client.post(
        "/api/v1/auth/local-login", {}, format="json", HTTP_HOST="127.0.0.1"
    ).status_code == 200
    session = client.session
    session["recent_auth_until"] = (timezone.now() + timedelta(minutes=5)).isoformat()
    session.save()
    return client


@pytest.mark.django_db
def test_system_exposes_automation_defaults_without_enabling_cloud_writes(system_client):
    body = system_client.get("/api/v1/system").json()
    assert body.get("node_pool_sync") == {
        "enabled": False,
        "interval_minutes": 15,
        "creation_templates": [],
        "last_scheduled_at": None,
        "source": "DEFAULT",
    }
    assert body.get("node_daily_restart") == {
        "enabled": False,
        "time": "04:00",
        "timezone": "Asia/Shanghai",
        "last_scheduled_at": None,
        "source": "DEFAULT",
    }
    assert body.get("usage_sync") == {
        "enabled": True,
        "interval_minutes": 1,
        "last_scheduled_at": None,
        "source": "DEFAULT",
    }


@pytest.mark.django_db
def test_system_persists_configurable_automation_and_rejects_partial_invalid_patch(
    system_client, cloud_account
):
    NodePool.objects.create(name="automation-pool", region="us-east-1", quota=1)
    template = {
        "region": "us-east-1",
        "cloud_account_id": str(cloud_account.pk),
        "plan_id": "nano",
        "image_id": "debian-12",
    }
    response = system_client.patch(
        "/api/v1/system",
        {
            "node_pool_sync_enabled": True,
            "node_pool_sync_creation_templates": [template],
            "node_pool_sync_interval_minutes": 5,
            "node_daily_restart_enabled": True,
            "node_daily_restart_time": "05:30",
            "node_daily_restart_timezone": "America/New_York",
            "usage_sync_interval_minutes": 10,
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["node_pool_sync"]["creation_templates"] == [template]
    assert response.json()["node_daily_restart"]["time"] == "05:30"
    invalid = system_client.patch(
        "/api/v1/system",
        {
            "provider_identity_network_enabled": False,
            "node_pool_sync_enabled": False,
            "node_daily_restart_time": "25:00",
        },
        format="json",
    )
    assert invalid.status_code == 400
    body = system_client.get("/api/v1/system").json()
    assert body["node_pool_sync"]["enabled"] is True
    assert body["provider_identity_network"]["source"] == "ENVIRONMENT"


@pytest.mark.django_db
@pytest.mark.parametrize("field,value", [
    ("node_pool_sync_interval_minutes", True),
    ("node_pool_sync_interval_minutes", 0),
    ("usage_sync_interval_minutes", 1441),
    ("node_daily_restart_timezone", "invalid-zone"),
    ("node_daily_restart_time", "4:00"),
    ("node_daily_restart_enabled", 1),
])
def test_automation_rejects_invalid_values(system_client, field, value):
    response = system_client.patch("/api/v1/system", {field: value}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_enabling_destructive_automation_requires_recent_step_up(system_client):
    session = system_client.session
    session.pop("recent_auth_until", None)
    session.save()
    response = system_client.patch(
        "/api/v1/system", {"node_pool_sync_enabled": True}, format="json"
    )
    assert response.status_code == 403
    assert response.json()["code"] == "STEP_UP_REQUIRED"


@pytest.mark.django_db
def test_region_quota_can_be_lowered_without_releasing_existing_nodes(prepared_node):
    node, _ = prepared_node
    set_allocations(node.pool_id, [{"region": node.region, "quota": 0}])
    node.refresh_from_db()
    assert NodePoolRegionAllocation.objects.get(pool=node.pool).quota == 0
    assert node.consumes_quota is True
    assert node.desired_state == "PRESENT"


def _ready_node(node):
    node.external_id = node.deterministic_name
    node.provisioning_state = "READY"
    node.raw_cloud_state = "running"
    node.addresses = ["192.0.2.10"]
    node.save()
    NodeResource.objects.create(
        node=node,
        kind="instance",
        external_id=node.external_id,
        ownership_tags={
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        },
        cost_status="ACTIVE",
    )
    Operation.objects.filter(target_id=node.pk).update(status="SUCCEEDED")
    return node


def _sibling(node, name, region=None):
    sibling = ManagedNode.objects.create(
        pool=node.pool, cloud_account=node.cloud_account,
        cloud_credential_version=node.cloud_credential_version,
        region=region or node.region, plan_id=node.plan_id, image_id=node.image_id,
        deterministic_name=name, operation_key=uuid4(), external_id=name,
        provisioning_state="READY", raw_cloud_state="running", addresses=["192.0.2.11"],
    )
    NodeResource.objects.create(
        node=sibling,
        kind="instance",
        external_id=sibling.external_id,
        ownership_tags={
            "xray-manager": "true",
            "xray-node": str(sibling.pk),
            "xray-operation": str(sibling.operation_key),
        },
        cost_status="ACTIVE",
    )
    return sibling


def _rebootable_node(node):
    from apps.nodes.models import NodeConfigRevision

    node.desired_generation = node.applied_generation = 1
    node.health_state = "HEALTHY"
    node.save(
        update_fields=[
            "desired_generation",
            "applied_generation",
            "health_state",
            "updated_at",
        ]
    )
    NodeConfigRevision.objects.update_or_create(
        node=node,
        generation=node.applied_generation,
        defaults={
            "config_hash": "a" * 64,
            "xray_version": "26.3.27",
            "installer_version": "1.0.0",
            "bundle_hash": "test-bundle",
            "usable": True,
            "probe_result": {
                "generation": node.applied_generation,
                "app_health_passed": True,
                "accepted": True,
                "positive_control": True,
                "fresh_connection": True,
            },
        },
    )


def _publish_subscription_on_nodes(profile_name, nodes):
    from apps.nodes.models import NodeConfigRevision, NodeProtocol
    from apps.subscriptions.credentials import CredentialService
    from apps.subscriptions.models import AccessProfile
    from apps.subscriptions.publishing import Publisher
    from apps.subscriptions.tokens import TokenService

    profile = AccessProfile.objects.create(name=profile_name)
    issued = TokenService.issue(profile.pk)
    for node in nodes:
        node.addresses = [
            {"value": "192.0.2.10", "family": 4, "kind": "dynamic"}
        ]
        node.save(update_fields=["addresses", "updated_at"])
        protocol = NodeProtocol.objects.create(
            node=node, protocol="vless", port=18443, credential_scope="profile"
        )
        credential = CredentialService.rotate(
            node.pk, profile_ids=[profile.pk], protocol_ids=[protocol.pk]
        )[0]
        node.refresh_from_db()
        node.applied_generation = node.desired_generation
        node.health_state = "HEALTHY"
        node.save(
            update_fields=[
                "applied_generation",
                "health_state",
                "updated_at",
            ]
        )
        credential.applied_generation = node.applied_generation
        credential.save(update_fields=["applied_generation"])
        NodeConfigRevision.objects.update_or_create(
            node=node,
            generation=node.applied_generation,
            defaults={
                "config_hash": "a" * 64,
                "xray_version": "26.3.27",
                "installer_version": "1.0.0",
                "bundle_hash": "test-bundle",
                "usable": True,
                "probe_result": {
                    "generation": node.applied_generation,
                    "app_health_passed": True,
                    "accepted": True,
                    "positive_control": True,
                    "fresh_connection": True,
                },
            },
        )
    Publisher.publish(issued.subscription_id)
    return profile.subscription


@pytest.mark.django_db
def test_pool_sync_submits_only_oldest_same_region_delete_and_skips_inflight(prepared_node):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.automation import validate_automated_delete
    from apps.nodes.tasks import schedule_node_pool_sync

    node, operation = prepared_node
    _ready_node(node)
    younger = _sibling(node, "younger")
    _sibling(node, "other-region", "ap-southeast-1")
    ManagedNode.objects.filter(pk=node.pk).update(created_at=timezone.now()-timedelta(days=2))
    set_allocations(node.pool_id, [
        {"region": node.region, "quota": 1},
        {"region": "ap-southeast-1", "quota": 1},
    ])
    setting = NodeAutomationSetting.objects.create(pool_sync_enabled=True)
    result = schedule_node_pool_sync()
    assert result["deleted"] == 1
    deletion = Operation.objects.get(kind="node.delete")
    assert deletion.target_id == node.pk
    assert deletion.preview.consumed_at is not None
    assert deletion.params["automation"]["policy_version"] == setting.policy_version
    validate_automated_delete(deletion, node, setting.policy_version)
    assert not Operation.objects.filter(target_id=younger.pk, kind="node.delete").exists()

    from apps.nodes.automation import node_delete_snapshot
    from apps.operations.services import ActionPreviewService, OperationService

    params = {
        "region": younger.region,
        "account_id": str(younger.cloud_account_id),
        "confirmation": "确认删除服务器",
        "automation": {"kind": "pool_sync", "policy_version": setting.policy_version},
    }
    preview = ActionPreviewService.create(
        admin=operation.admin,
        kind="node.delete",
        target_id=younger.pk,
        params=params,
        snapshot=node_delete_snapshot(younger),
        required_phrase="确认删除服务器",
    )
    newer_delete = OperationService.submit(
        kind="node.delete",
        target_id=younger.pk,
        params=params,
        key=uuid4(),
        preview_id=preview.pk,
        admin=operation.admin,
        cloud_credential_version=younger.cloud_credential_version,
    )
    with pytest.raises(DomainError) as not_oldest:
        validate_automated_delete(newer_delete, younger, setting.policy_version)
    assert not_oldest.value.code == "AUTOMATION_OVERAGE_CHANGED"

    allocation = node.pool.region_allocations.get(region=node.region)
    allocation.quota = 2
    allocation.save(update_fields=["quota", "updated_at"])
    with pytest.raises(DomainError) as stale:
        validate_automated_delete(deletion, node, setting.policy_version)
    assert stale.value.code == "AUTOMATION_OVERAGE_CHANGED"
    setting.pool_sync_last_scheduled_at = timezone.now()-timedelta(hours=1)
    setting.save()
    assert schedule_node_pool_sync()["deleted"] == 0
    assert Operation.objects.filter(kind="node.delete").count() == 2


@pytest.mark.django_db
def test_pool_sync_blocks_deleting_the_only_publishable_subscription_node(prepared_node):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_node_pool_sync

    node, _operation = prepared_node
    _ready_node(node)
    subscription = _publish_subscription_on_nodes("single-endpoint", [node])
    set_allocations(node.pool_id, [{"region": node.region, "quota": 0}])
    NodeAutomationSetting.objects.create(pool_sync_enabled=True)

    result = schedule_node_pool_sync()

    assert result["deleted"] == 0
    assert result["blocked"] == 1
    assert not Operation.objects.filter(kind="node.delete").exists()
    subscription.refresh_from_db()
    assert subscription.current_revision.usable is True


@pytest.mark.django_db
def test_pool_sync_allows_oldest_delete_when_subscription_has_another_endpoint(
    prepared_node,
):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_node_pool_sync

    oldest, _operation = prepared_node
    _ready_node(oldest)
    younger = _sibling(oldest, "younger")
    _publish_subscription_on_nodes("redundant-endpoints", [oldest, younger])
    ManagedNode.objects.filter(pk=oldest.pk).update(
        created_at=timezone.now() - timedelta(days=2)
    )
    set_allocations(oldest.pool_id, [{"region": oldest.region, "quota": 1}])
    NodeAutomationSetting.objects.create(pool_sync_enabled=True)

    result = schedule_node_pool_sync()

    assert result["deleted"] == 1
    deletion = Operation.objects.get(kind="node.delete")
    assert deletion.target_id == oldest.pk


@pytest.mark.django_db
def test_automated_delete_rechecks_subscription_fallback_before_cloud_write(prepared_node):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.automation import validate_automated_delete
    from apps.nodes.tasks import schedule_node_pool_sync

    oldest, _operation = prepared_node
    _ready_node(oldest)
    younger = _sibling(oldest, "younger")
    _publish_subscription_on_nodes("changing-fallback", [oldest, younger])
    ManagedNode.objects.filter(pk=oldest.pk).update(
        created_at=timezone.now() - timedelta(days=2)
    )
    set_allocations(oldest.pool_id, [{"region": oldest.region, "quota": 1}])
    setting = NodeAutomationSetting.objects.create(pool_sync_enabled=True)

    assert schedule_node_pool_sync()["deleted"] == 1
    deletion = Operation.objects.get(kind="node.delete")
    younger.health_state = "UNHEALTHY"
    younger.save(update_fields=["health_state", "updated_at"])

    with pytest.raises(DomainError) as blocked:
        validate_automated_delete(deletion, oldest, setting.policy_version)

    assert blocked.value.code == "AUTOMATION_SUBSCRIPTION_FALLBACK_REQUIRED"


@pytest.mark.django_db
def test_pool_sync_does_not_skip_oldest_ineligible_quota_consumer(prepared_node):
    from apps.nodes.tasks import schedule_node_pool_sync

    oldest, _operation = prepared_node
    oldest.external_id = oldest.deterministic_name
    oldest.provisioning_state = "PROVISIONED"
    oldest.save(update_fields=["external_id", "provisioning_state", "updated_at"])
    younger = _sibling(oldest, "younger")
    ManagedNode.objects.filter(pk=oldest.pk).update(created_at=timezone.now() - timedelta(days=2))
    ManagedNode.objects.filter(pk=younger.pk).update(created_at=timezone.now() - timedelta(days=1))
    set_allocations(oldest.pool_id, [{"region": oldest.region, "quota": 1}])
    NodeAutomationSetting.objects.create(pool_sync_enabled=True)

    result = schedule_node_pool_sync()

    assert result["deleted"] == 0
    assert result["blocked"] == 1
    assert not Operation.objects.filter(kind="node.delete").exists()


@pytest.mark.django_db
def test_pool_sync_reserves_exact_deficit_and_never_duplicates_unknown_create(prepared_node):
    from apps.nodes.tasks import schedule_node_pool_sync

    node, operation = prepared_node
    NodeAutomationSetting.objects.create(
        pool_sync_enabled=True,
        pool_sync_creation_templates=[
            {
                "region": node.region,
                "cloud_account_id": str(node.cloud_account_id),
                "plan_id": "nano",
                "image_id": "debian-12",
            }
        ],
    )
    operation.status = "NEEDS_RECONCILIATION"
    operation.save()
    first = schedule_node_pool_sync()
    assert first["created"] == 2
    assert ManagedNode.objects.filter(consumes_quota=True).count() == 3
    assert Operation.objects.filter(kind="node.create", status="PENDING").count() == 2
    NodeAutomationSetting.objects.update(pool_sync_last_scheduled_at=None)
    second = schedule_node_pool_sync()
    assert second["created"] == 0
    assert ManagedNode.objects.filter(consumes_quota=True).count() == 3


@pytest.mark.django_db
def test_daily_restart_runs_one_at_boundary_and_rotates_on_next_local_day(
    prepared_node, monkeypatch
):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.automation import validate_automated_restart
    from apps.nodes.tasks import schedule_daily_node_restart

    node, _ = prepared_node
    _ready_node(node)
    _rebootable_node(node)
    younger = _sibling(node, "younger")
    _rebootable_node(younger)
    ManagedNode.objects.filter(pk=node.pk).update(created_at=timezone.now()-timedelta(days=2))
    NodeAutomationSetting.objects.create(daily_restart_enabled=True)
    monkeypatch.setattr("apps.nodes.probes.configured_health_probe", lambda: lambda _node: {})
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 5, 19, 59, 59, tzinfo=UTC),
    )
    assert schedule_daily_node_restart()["scheduled"] == 0
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 5, 20, 0, tzinfo=UTC),
    )
    assert schedule_daily_node_restart()["scheduled"] == 1
    reboot = Operation.objects.get(kind="node.reboot")
    assert reboot.target_id == node.pk
    validate_automated_restart(reboot, node, reboot.params["automation"]["policy_version"])
    setting = NodeAutomationSetting.objects.get(singleton_key=1)
    setting.policy_version += 1
    setting.save(update_fields=["policy_version", "updated_at"])
    with pytest.raises(DomainError) as stale:
        validate_automated_restart(reboot, node, reboot.params["automation"]["policy_version"])
    assert stale.value.code == "AUTOMATION_POLICY_STALE"
    assert schedule_daily_node_restart()["scheduled"] == 0
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 6, 20, 0, tzinfo=UTC),
    )
    next_day = schedule_daily_node_restart()
    assert next_day["scheduled"] == 0
    assert next_day["in_flight"] is True
    reboot.status = "SUCCEEDED"
    reboot.save()
    assert schedule_daily_node_restart()["scheduled"] == 1
    assert Operation.objects.filter(kind="node.reboot", target_id=younger.pk).exists()


@pytest.mark.django_db
def test_daily_restart_blocks_when_health_probe_is_unavailable(prepared_node, monkeypatch):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_daily_node_restart

    node, _ = prepared_node
    _ready_node(node)
    _rebootable_node(node)
    setting = NodeAutomationSetting.objects.create(daily_restart_enabled=True)
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 6, 20, 0, tzinfo=UTC),
    )
    monkeypatch.setattr("apps.nodes.probes.configured_health_probe", lambda: None)

    result = schedule_daily_node_restart()

    assert result == {"scheduled": 0, "blocked": "HEALTH_PROBE_UNAVAILABLE"}
    setting.refresh_from_db()
    assert setting.daily_restart_last_local_date is None
    assert not Operation.objects.filter(kind="node.reboot").exists()


@pytest.mark.django_db
def test_daily_restart_fall_back_hour_runs_once_per_local_date(prepared_node, monkeypatch):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_daily_node_restart

    node, _ = prepared_node
    _ready_node(node)
    _rebootable_node(node)
    NodeAutomationSetting.objects.create(
        daily_restart_enabled=True,
        daily_restart_time="01:30",
        daily_restart_timezone="America/New_York",
    )
    monkeypatch.setattr("apps.nodes.probes.configured_health_probe", lambda: lambda _node: {})
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
    )
    assert schedule_daily_node_restart()["scheduled"] == 1
    Operation.objects.filter(kind="node.reboot").update(status="SUCCEEDED")
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
    )
    repeated_hour = schedule_daily_node_restart()
    assert repeated_hour["scheduled"] == 0
    assert repeated_hour["local_date"] == "2026-11-01"
    assert Operation.objects.filter(kind="node.reboot").count() == 1
