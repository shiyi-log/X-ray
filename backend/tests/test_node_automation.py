from datetime import datetime, timedelta, timezone as dt_timezone
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import NodeAutomationSetting
from apps.nodes.models import ManagedNode, NodePoolRegionAllocation
from apps.nodes.quota import set_allocations
from apps.operations.models import Operation


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
    Operation.objects.filter(target_id=node.pk).update(status="SUCCEEDED")
    return node


def _sibling(node, name, region=None):
    return ManagedNode.objects.create(
        pool=node.pool, cloud_account=node.cloud_account,
        cloud_credential_version=node.cloud_credential_version,
        region=region or node.region, plan_id=node.plan_id, image_id=node.image_id,
        deterministic_name=name, operation_key=uuid4(), external_id=name,
        provisioning_state="READY", raw_cloud_state="running", addresses=["192.0.2.11"],
    )


@pytest.mark.django_db
def test_pool_sync_submits_only_oldest_same_region_delete_and_skips_inflight(prepared_node):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_node_pool_sync

    node, _ = prepared_node
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
    assert not Operation.objects.filter(target_id=younger.pk, kind="node.delete").exists()
    setting.pool_last_scheduled_at = timezone.now()-timedelta(hours=1)
    setting.save()
    assert schedule_node_pool_sync()["deleted"] == 0
    assert Operation.objects.filter(kind="node.delete").count() == 1


@pytest.mark.django_db
def test_pool_sync_reserves_exact_deficit_and_never_duplicates_unknown_create(prepared_node):
    from apps.nodes.tasks import schedule_node_pool_sync

    node, operation = prepared_node
    NodeAutomationSetting.objects.create(
        pool_sync_enabled=True,
        creation_templates=[{"region": node.region, "cloud_account_id": str(node.cloud_account_id),
                             "plan_id": "nano", "image_id": "debian-12"}],
    )
    operation.status = "NEEDS_RECONCILIATION"
    operation.save()
    first = schedule_node_pool_sync()
    assert first["created"] == 2
    assert ManagedNode.objects.filter(consumes_quota=True).count() == 3
    assert Operation.objects.filter(kind="node.create", status="PENDING").count() == 2
    NodeAutomationSetting.objects.update(pool_last_scheduled_at=None)
    second = schedule_node_pool_sync()
    assert second["created"] == 0
    assert ManagedNode.objects.filter(consumes_quota=True).count() == 3


@pytest.mark.django_db
def test_daily_restart_runs_one_at_boundary_and_rotates_on_next_local_day(prepared_node, monkeypatch):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_daily_node_restart

    node, _ = prepared_node
    _ready_node(node)
    younger = _sibling(node, "younger")
    ManagedNode.objects.filter(pk=node.pk).update(created_at=timezone.now()-timedelta(days=2))
    NodeAutomationSetting.objects.create(daily_restart_enabled=True)
    monkeypatch.setattr("apps.nodes.automation.timezone.now", lambda: datetime(2026, 11, 5, 19, 59, 59, tzinfo=dt_timezone.utc))
    assert schedule_daily_node_restart()["scheduled"] == 0
    monkeypatch.setattr("apps.nodes.automation.timezone.now", lambda: datetime(2026, 11, 5, 20, 0, tzinfo=dt_timezone.utc))
    assert schedule_daily_node_restart()["scheduled"] == 1
    reboot = Operation.objects.get(kind="node.reboot")
    assert reboot.target_id == node.pk
    assert schedule_daily_node_restart()["scheduled"] == 0
    reboot.status = "SUCCEEDED"
    reboot.save()
    monkeypatch.setattr("apps.nodes.automation.timezone.now", lambda: datetime(2026, 11, 6, 20, 0, tzinfo=dt_timezone.utc))
    assert schedule_daily_node_restart()["scheduled"] == 1
    assert Operation.objects.filter(kind="node.reboot", target_id=younger.pk).exists()
