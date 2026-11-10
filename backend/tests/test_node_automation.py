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
    node.addresses = [
        {
            "value": "192.0.2.10",
            "family": 4,
            "kind": "dynamic",
            "resource_id": node.external_id,
        }
    ]
    node.save(
        update_fields=[
            "desired_generation",
            "applied_generation",
            "health_state",
            "addresses",
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
def test_pool_sync_submits_only_one_global_oldest_delete_across_over_quota_regions(
    prepared_node,
):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_node_pool_sync

    east_oldest, _operation = prepared_node
    _ready_node(east_oldest)
    nodes = [
        east_oldest,
        _sibling(east_oldest, "east-younger"),
        _sibling(east_oldest, "ap-oldest", "ap-southeast-1"),
        _sibling(east_oldest, "ap-younger", "ap-southeast-1"),
    ]
    created_at = timezone.now() - timedelta(days=4)
    for position, node in enumerate(nodes):
        ManagedNode.objects.filter(pk=node.pk).update(
            created_at=created_at + timedelta(days=position)
        )
    _publish_subscription_on_nodes("multi-region-pool-sync", nodes)
    set_allocations(
        east_oldest.pool_id,
        [
            {"region": "ap-southeast-1", "quota": 1},
            {"region": "us-east-1", "quota": 1},
        ],
    )
    NodeAutomationSetting.objects.create(pool_sync_enabled=True)

    result = schedule_node_pool_sync()

    deletes = list(Operation.objects.filter(kind="node.delete"))
    assert result["deleted"] == 1
    assert len(deletes) == 1
    assert deletes[0].target_id == east_oldest.pk


@pytest.mark.django_db
def test_pool_sync_deletes_one_oldest_per_due_cycle_until_quota_two(prepared_node):
    from apps.nodes.tasks import schedule_node_pool_sync

    oldest, _create_operation = prepared_node
    _ready_node(oldest)
    nodes = [
        oldest,
        _sibling(oldest, "second"),
        _sibling(oldest, "third"),
        _sibling(oldest, "fourth"),
    ]
    created_at = timezone.now() - timedelta(days=4)
    for position, node in enumerate(nodes):
        ManagedNode.objects.filter(pk=node.pk).update(
            created_at=created_at + timedelta(days=position)
        )
    _publish_subscription_on_nodes("quota-two-cycle", nodes)
    set_allocations(oldest.pool_id, [{"region": oldest.region, "quota": 2}])
    setting = NodeAutomationSetting.objects.create(pool_sync_enabled=True)
    consumers = ManagedNode.objects.filter(
        pool=oldest.pool,
        region=oldest.region,
        consumes_quota=True,
    )
    assert consumers.count() == 4

    first_cycle = schedule_node_pool_sync()

    assert first_cycle["deleted"] == 1
    first_delete = Operation.objects.get(kind="node.delete")
    assert first_delete.target_id == nodes[0].pk

    setting.pool_sync_last_scheduled_at = timezone.now() - timedelta(
        minutes=setting.pool_sync_interval_minutes
    )
    setting.save(update_fields=["pool_sync_last_scheduled_at", "updated_at"])
    pending_cycle = schedule_node_pool_sync()

    assert pending_cycle["deleted"] == 0
    assert pending_cycle["skipped"] == 1
    setting.refresh_from_db()
    assert setting.pool_sync_last_scheduled_at < timezone.now() - timedelta(
        minutes=setting.pool_sync_interval_minutes
    )
    assert Operation.objects.filter(kind="node.delete").count() == 1

    # The lifecycle read-back path is covered separately; model its confirmed result here.
    ManagedNode.objects.filter(pk=nodes[0].pk).update(
        consumes_quota=False,
        desired_state="DELETED",
        provisioning_state="DELETED",
    )
    Operation.objects.filter(pk=first_delete.pk).update(status="SUCCEEDED")
    assert consumers.count() == 3
    setting.pool_sync_last_scheduled_at = timezone.now() - timedelta(
        minutes=setting.pool_sync_interval_minutes
    )
    setting.save(update_fields=["pool_sync_last_scheduled_at", "updated_at"])
    next_cycle = schedule_node_pool_sync()

    assert next_cycle["deleted"] == 1
    deletes = list(Operation.objects.filter(kind="node.delete").order_by("created_at"))
    assert [item.target_id for item in deletes] == [nodes[0].pk, nodes[1].pk]

    ManagedNode.objects.filter(pk=nodes[1].pk).update(
        consumes_quota=False,
        desired_state="DELETED",
        provisioning_state="DELETED",
    )
    Operation.objects.filter(pk=deletes[1].pk).update(status="SUCCEEDED")
    remaining = ManagedNode.objects.filter(
        pool=oldest.pool,
        region=oldest.region,
        consumes_quota=True,
    ).count()
    assert remaining == 2


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
def test_pool_delete_skips_fallback_for_confirmed_revoked_current_token(prepared_node):
    from apps.nodes.automation import has_subscription_endpoint_fallback
    from apps.subscriptions.models import SubscriptionToken
    from apps.subscriptions.tokens import TokenService

    node, _operation = prepared_node
    _ready_node(node)
    subscription = _publish_subscription_on_nodes("revoked-current-token", [node])
    token = SubscriptionToken.objects.get(subscription=subscription)
    TokenService.revoke_token(subscription.pk, token.pk)

    assert has_subscription_endpoint_fallback(node) is True


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
def test_automated_delete_dispatch_rejects_lost_subscription_fallback(prepared_node):
    from types import SimpleNamespace

    from apps.nodes.lifecycle import NodeLifecycle
    from apps.nodes.tasks import schedule_node_pool_sync

    oldest, _operation = prepared_node
    _ready_node(oldest)
    younger = _sibling(oldest, "younger")
    _publish_subscription_on_nodes("dispatch-changing-fallback", [oldest, younger])
    ManagedNode.objects.filter(pk=oldest.pk).update(
        created_at=timezone.now() - timedelta(days=2)
    )
    set_allocations(oldest.pool_id, [{"region": oldest.region, "quota": 1}])
    NodeAutomationSetting.objects.create(pool_sync_enabled=True)
    assert schedule_node_pool_sync()["deleted"] == 1
    deletion = Operation.objects.get(kind="node.delete")

    younger.health_state = "UNHEALTHY"
    younger.save(update_fields=["health_state", "updated_at"])

    class WriteRecorder:
        def __init__(self):
            self.delete_calls = 0

        def delete_instance(self, _resource, *, permit):
            self.delete_calls += 1
            return SimpleNamespace(outcome="accepted", request_id="fake")

        def get_instance(self, resource):
            return SimpleNamespace(ref=resource)

    provider = WriteRecorder()
    NodeLifecycle(provider_factory=lambda _node, _authorizer: provider).dispatch(
        "delete", oldest.pk, operation_id=deletion.pk
    )

    deletion.refresh_from_db()
    assert provider.delete_calls == 0
    assert deletion.status == "FAILED"
    assert deletion.error_code == "AUTOMATION_SUBSCRIPTION_FALLBACK_REQUIRED"


@pytest.mark.django_db
def test_pool_sync_requires_fallback_for_each_existing_subscription_format(prepared_node):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.models import NodeConfigRevision, NodeProtocol
    from apps.nodes.tasks import schedule_node_pool_sync
    from apps.subscriptions.credentials import CredentialService
    from apps.subscriptions.models import NodeCredential
    from apps.subscriptions.publishing import Publisher

    oldest, _operation = prepared_node
    _ready_node(oldest)
    younger = _sibling(oldest, "younger")
    subscription = _publish_subscription_on_nodes(
        "format-fallback", [oldest, younger]
    )
    shadowsocks = NodeProtocol.objects.create(
        node=oldest,
        protocol="shadowsocks",
        port=18444,
        credential_scope="profile",
    )
    credential = CredentialService.rotate(
        oldest.pk,
        profile_ids=[subscription.profile_id],
        protocol_ids=[shadowsocks.pk],
    )[0]
    oldest.refresh_from_db()
    generation = oldest.desired_generation
    NodeCredential.objects.filter(
        node=oldest, profile_id=subscription.profile_id, revoked_at__isnull=True
    ).update(desired_generation=generation, applied_generation=generation)
    NodeCredential.objects.filter(pk=credential.pk).update(applied_generation=generation)
    oldest.applied_generation = generation
    oldest.health_state = "HEALTHY"
    oldest.save(update_fields=["applied_generation", "health_state", "updated_at"])
    NodeConfigRevision.objects.update_or_create(
        node=oldest,
        generation=generation,
        defaults={
            "config_hash": "b" * 64,
            "xray_version": "26.3.27",
            "installer_version": "1.0.0",
            "bundle_hash": "test-bundle",
            "usable": True,
            "probe_result": {
                "generation": generation,
                "app_health_passed": True,
                "accepted": True,
                "positive_control": True,
                "fresh_connection": True,
            },
        },
    )
    Publisher.publish(subscription.pk)
    subscription.refresh_from_db()
    assert "clash" in subscription.current_revision.payloads

    ManagedNode.objects.filter(pk=oldest.pk).update(
        created_at=timezone.now() - timedelta(days=2)
    )
    set_allocations(oldest.pool_id, [{"region": oldest.region, "quota": 1}])
    NodeAutomationSetting.objects.create(pool_sync_enabled=True)

    result = schedule_node_pool_sync()

    assert result["deleted"] == 0
    assert result["blocked"] == 1
    assert not Operation.objects.filter(kind="node.delete").exists()


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
    stop = Operation.objects.get(kind="node.stop")
    assert stop.target_id == node.pk
    validate_automated_restart(stop, node, stop.params["automation"]["policy_version"])
    setting = NodeAutomationSetting.objects.get(singleton_key=1)
    setting.policy_version += 1
    setting.save(update_fields=["policy_version", "updated_at"])
    with pytest.raises(DomainError) as stale:
        validate_automated_restart(stop, node, stop.params["automation"]["policy_version"])
    assert stale.value.code == "AUTOMATION_POLICY_STALE"
    assert schedule_daily_node_restart()["in_flight"] is True
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 6, 20, 0, tzinfo=UTC),
    )
    next_day = schedule_daily_node_restart()
    assert next_day["scheduled"] == 0
    assert next_day["in_flight"] is True
    stop.status = "SUCCEEDED"
    stop.save()
    ManagedNode.objects.filter(pk=node.pk).update(
        raw_cloud_state="stopped", health_state="UNKNOWN"
    )
    continued = schedule_daily_node_restart()
    start = Operation.objects.get(pk=continued["operation_id"])
    assert continued["phase"] == "start"
    assert start.kind == "node.start"
    assert start.params["automation"]["local_date"] == "2026-11-06"
    start.status = "SUCCEEDED"
    start.save()
    ManagedNode.objects.filter(pk=node.pk).update(
        raw_cloud_state="running", health_state="HEALTHY"
    )
    assert schedule_daily_node_restart()["scheduled"] == 1
    assert Operation.objects.filter(kind="node.stop", target_id=younger.pk).exists()


@pytest.mark.django_db
def test_daily_restart_uses_stop_start_phases_and_advances_after_start_success(
    prepared_node, monkeypatch
):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_daily_node_restart

    oldest, _ = prepared_node
    _ready_node(oldest)
    _rebootable_node(oldest)
    younger = _sibling(oldest, "younger")
    _rebootable_node(younger)
    ManagedNode.objects.filter(pk=oldest.pk).update(
        created_at=timezone.now() - timedelta(days=2)
    )
    setting = NodeAutomationSetting.objects.create(daily_restart_enabled=True)
    monkeypatch.setattr("apps.nodes.probes.configured_health_probe", lambda: lambda _node: {})
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 5, 20, 0, tzinfo=UTC),
    )

    first = schedule_daily_node_restart()
    stop = Operation.objects.get(pk=first["operation_id"])
    assert stop.kind == "node.stop"
    assert stop.params["automation"]["phase"] == "stop"
    assert stop.params["automation"]["local_date"] == "2026-11-06"

    stop.status = "SUCCEEDED"
    stop.save(update_fields=["status", "updated_at"])
    ManagedNode.objects.filter(pk=oldest.pk).update(
        raw_cloud_state="stopped", health_state="UNKNOWN"
    )
    setting.daily_restart_enabled = False
    setting.policy_version += 1
    setting.save(update_fields=["daily_restart_enabled", "policy_version", "updated_at"])
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 6, 22, 0, tzinfo=UTC),
    )
    continued = schedule_daily_node_restart()
    start = Operation.objects.get(pk=continued["operation_id"])
    assert continued["scheduled"] == 1
    assert start.kind == "node.start"
    assert start.target_id == oldest.pk
    assert start.params["automation"]["phase"] == "start"
    assert start.params["automation"]["local_date"] == "2026-11-06"
    setting.daily_restart_enabled = True
    setting.policy_version += 1
    setting.save(update_fields=["daily_restart_enabled", "policy_version", "updated_at"])

    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 6, 20, 0, tzinfo=UTC),
    )
    assert schedule_daily_node_restart()["in_flight"] is True

    start.status = "SUCCEEDED"
    start.save(update_fields=["status", "updated_at"])
    ManagedNode.objects.filter(pk=oldest.pk).update(
        raw_cloud_state="running", health_state="HEALTHY"
    )
    next_day = schedule_daily_node_restart()
    next_stop = Operation.objects.get(pk=next_day["operation_id"])
    assert next_day["scheduled"] == 1
    assert next_stop.kind == "node.stop"
    assert next_stop.target_id == younger.pk


@pytest.mark.django_db
def test_daily_restart_blocks_rotation_after_failed_start(prepared_node, monkeypatch):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_daily_node_restart

    oldest, _ = prepared_node
    _ready_node(oldest)
    _rebootable_node(oldest)
    younger = _sibling(oldest, "younger")
    _rebootable_node(younger)
    NodeAutomationSetting.objects.create(daily_restart_enabled=True)
    monkeypatch.setattr("apps.nodes.probes.configured_health_probe", lambda: lambda _node: {})
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 5, 20, 0, tzinfo=UTC),
    )

    stop = Operation.objects.get(
        pk=schedule_daily_node_restart()["operation_id"]
    )
    stop.status = "SUCCEEDED"
    stop.save(update_fields=["status", "updated_at"])
    ManagedNode.objects.filter(pk=oldest.pk).update(
        raw_cloud_state="stopped", health_state="UNKNOWN"
    )
    start = Operation.objects.get(
        pk=schedule_daily_node_restart()["operation_id"]
    )
    start.status = "FAILED"
    start.save(update_fields=["status", "updated_at"])
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 6, 20, 0, tzinfo=UTC),
    )

    result = schedule_daily_node_restart()

    assert result == {
        "scheduled": 0,
        "blocked": "RESTART_RECOVERY_REQUIRED",
        "node_id": str(oldest.pk),
    }
    assert not Operation.objects.filter(kind="node.stop", target_id=younger.pk).exists()


@pytest.mark.django_db
def test_daily_restart_blocks_instead_of_skipping_failed_stop_target(prepared_node, monkeypatch):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_daily_node_restart

    oldest, _ = prepared_node
    _ready_node(oldest)
    _rebootable_node(oldest)
    younger = _sibling(oldest, "younger")
    _rebootable_node(younger)
    NodeAutomationSetting.objects.create(daily_restart_enabled=True)
    monkeypatch.setattr("apps.nodes.probes.configured_health_probe", lambda: lambda _node: {})
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 5, 20, 0, tzinfo=UTC),
    )

    stop = Operation.objects.get(pk=schedule_daily_node_restart()["operation_id"])
    stop.status = "FAILED"
    stop.save(update_fields=["status", "updated_at"])
    ManagedNode.objects.filter(pk=oldest.pk).update(
        raw_cloud_state="running",
        health_state="UNKNOWN",
        observation_error="CLOUD_OPERATION_FAILED",
    )
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 6, 20, 0, tzinfo=UTC),
    )

    result = schedule_daily_node_restart()

    assert result == {
        "scheduled": 0,
        "blocked": "RESTART_RECOVERY_REQUIRED",
        "node_id": str(oldest.pk),
    }
    assert not Operation.objects.filter(kind="node.stop", target_id=younger.pk).exists()


@pytest.mark.django_db
def test_daily_restart_accepts_audited_manual_recovery_after_failed_start(
    prepared_node, monkeypatch
):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_daily_node_restart
    from apps.operations.services import OperationService

    oldest, _ = prepared_node
    _ready_node(oldest)
    _rebootable_node(oldest)
    younger = _sibling(oldest, "younger")
    _rebootable_node(younger)
    NodeAutomationSetting.objects.create(daily_restart_enabled=True)
    monkeypatch.setattr("apps.nodes.probes.configured_health_probe", lambda: lambda _node: {})
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 5, 20, 0, tzinfo=UTC),
    )

    stop = Operation.objects.get(pk=schedule_daily_node_restart()["operation_id"])
    stop.status = "SUCCEEDED"
    stop.save(update_fields=["status", "updated_at"])
    ManagedNode.objects.filter(pk=oldest.pk).update(
        raw_cloud_state="stopped", health_state="UNKNOWN"
    )
    start = Operation.objects.get(pk=schedule_daily_node_restart()["operation_id"])
    start.status = "FAILED"
    start.save(update_fields=["status", "updated_at"])
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 6, 20, 0, tzinfo=UTC),
    )
    assert schedule_daily_node_restart()["blocked"] == "RESTART_RECOVERY_REQUIRED"

    manual_start = OperationService.submit(
        kind="node.start",
        target_id=oldest.pk,
        params={"region": oldest.region, "account_id": str(oldest.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=start.admin,
        cloud_credential_version=oldest.cloud_credential_version,
    )
    manual_start.status = "SUCCEEDED"
    manual_start.result = {"addresses_changed": True}
    manual_start.save(update_fields=["status", "result", "updated_at"])
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 6, 20, 0, 1, tzinfo=UTC),
    )
    manual_reboot = OperationService.submit(
        kind="node.reboot",
        target_id=oldest.pk,
        params={"region": oldest.region, "account_id": str(oldest.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=start.admin,
        cloud_credential_version=oldest.cloud_credential_version,
    )
    manual_reboot.status = "SUCCEEDED"
    manual_reboot.result = {"health_state": "HEALTHY"}
    manual_reboot.save(update_fields=["status", "result", "updated_at"])
    ManagedNode.objects.filter(pk=oldest.pk).update(
        raw_cloud_state="running",
        health_state="HEALTHY",
        observation_error="",
        addresses=[
            {
                "value": "198.51.100.44",
                "family": 4,
                "kind": "dynamic",
                "resource_id": oldest.external_id,
            }
        ],
    )

    recovered = schedule_daily_node_restart()

    assert recovered["scheduled"] == 1, recovered
    assert recovered["node_id"] == str(oldest.pk)
    assert recovered["phase"] == "stop"
    assert Operation.objects.get(pk=recovered["operation_id"]).target_id == oldest.pk


@pytest.mark.django_db
def test_daily_restart_does_not_advance_rotation_after_failed_attempt(
    prepared_node, monkeypatch
):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_daily_node_restart

    oldest, _ = prepared_node
    _ready_node(oldest)
    _rebootable_node(oldest)
    younger = _sibling(oldest, "younger")
    _rebootable_node(younger)
    NodeAutomationSetting.objects.create(daily_restart_enabled=True)
    monkeypatch.setattr("apps.nodes.probes.configured_health_probe", lambda: lambda _node: {})
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 5, 20, 0, tzinfo=UTC),
    )

    first = schedule_daily_node_restart()
    failed = Operation.objects.get(pk=first["operation_id"])
    failed.status = "FAILED"
    failed.save(update_fields=["status", "updated_at"])
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 6, 20, 0, tzinfo=UTC),
    )

    next_day = schedule_daily_node_restart()

    assert next_day["node_id"] == str(oldest.pk)
    assert next_day["node_id"] != str(younger.pk)


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
    assert not Operation.objects.filter(
        params__automation__kind="daily_restart"
    ).exists()


@pytest.mark.django_db
def test_daily_restart_skips_known_unhealthy_node_without_consuming_its_turn(
    prepared_node, monkeypatch
):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_daily_node_restart

    oldest, _ = prepared_node
    _ready_node(oldest)
    _rebootable_node(oldest)
    younger = _sibling(oldest, "younger")
    _rebootable_node(younger)
    ManagedNode.objects.filter(pk=oldest.pk).update(health_state="UNHEALTHY")
    setting = NodeAutomationSetting.objects.create(daily_restart_enabled=True)
    monkeypatch.setattr("apps.nodes.probes.configured_health_probe", lambda: lambda _node: {})
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 6, 20, 0, tzinfo=UTC),
    )

    result = schedule_daily_node_restart()

    setting.refresh_from_db()
    assert result["scheduled"] == 1
    assert result["node_id"] == str(younger.pk)
    assert setting.daily_restart_last_node_id == younger.pk
    assert Operation.objects.filter(kind="node.stop", target_id=oldest.pk).count() == 0

    stop = Operation.objects.get(kind="node.stop", target_id=younger.pk)
    ManagedNode.objects.filter(pk=younger.pk).update(health_state="UNHEALTHY")
    from apps.nodes.automation import validate_automated_restart

    with pytest.raises(DomainError) as error:
        validate_automated_restart(
            stop, younger, stop.params["automation"]["policy_version"]
        )
    assert error.value.code == "AUTOMATION_TARGET_INELIGIBLE"


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
    stop = Operation.objects.get(kind="node.stop")
    stop.status = "SUCCEEDED"
    stop.save(update_fields=["status", "updated_at"])
    ManagedNode.objects.filter(pk=node.pk).update(
        raw_cloud_state="stopped", health_state="UNKNOWN"
    )
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
    )
    repeated_hour = schedule_daily_node_restart()
    assert repeated_hour["scheduled"] == 1
    assert repeated_hour["phase"] == "start"
    start = Operation.objects.get(kind="node.start")
    start.status = "SUCCEEDED"
    start.save(update_fields=["status", "updated_at"])
    ManagedNode.objects.filter(pk=node.pk).update(
        raw_cloud_state="running", health_state="HEALTHY"
    )
    repeated_hour = schedule_daily_node_restart()
    assert repeated_hour["scheduled"] == 0
    assert repeated_hour["local_date"] == "2026-11-01"
    assert Operation.objects.filter(kind="node.stop").count() == 1


@pytest.mark.django_db
def test_daily_restart_schedules_after_spring_forward_skips_configured_time(
    prepared_node, monkeypatch
):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_daily_node_restart

    node, _ = prepared_node
    _ready_node(node)
    _rebootable_node(node)
    NodeAutomationSetting.objects.create(
        daily_restart_enabled=True,
        daily_restart_time="02:30",
        daily_restart_timezone="America/New_York",
    )
    monkeypatch.setattr("apps.nodes.probes.configured_health_probe", lambda: lambda _node: {})
    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 3, 8, 6, 59, 59, tzinfo=UTC),
    )
    assert schedule_daily_node_restart()["scheduled"] == 0

    monkeypatch.setattr(
        "apps.nodes.automation.timezone.now",
        lambda: datetime(2026, 3, 8, 7, 0, tzinfo=UTC),
    )
    result = schedule_daily_node_restart()

    assert result["scheduled"] == 1
    assert result["local_date"] == "2026-03-08"
    assert Operation.objects.get(kind="node.stop").target_id == node.pk
