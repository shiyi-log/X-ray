import io
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.mark.django_db
def test_one_shot_collection_targets_only_the_requested_ready_node(ready_node, monkeypatch):
    from apps.nodes.quota import reserve_node
    from apps.subscriptions import metering

    ready_node.external_id = "target-instance"
    ready_node.save(update_fields=["external_id", "updated_at"])
    other = reserve_node(
        ready_node.pool_id,
        account_id=ready_node.cloud_account_id,
        region=ready_node.region,
        plan_id=ready_node.plan_id,
        image_id=ready_node.image_id,
        operation_key=uuid4(),
    )
    other.external_id = "other-instance"
    other.provisioning_state = "READY"
    other.save(update_fields=["external_id", "provisioning_state", "updated_at"])
    seen = []

    def collect(node, *, fetcher=None):
        seen.append((node.pk, fetcher))
        return 2

    monkeypatch.setattr(metering, "collect_node", collect)
    fetcher = object()

    result = metering.collect_node_once(ready_node.pk, fetcher=fetcher)

    assert result == 2
    assert seen == [(ready_node.pk, fetcher)]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field,value",
    [
        ("provisioning_state", "PROVISIONED"),
        ("desired_state", "STOPPED"),
        ("security_state", "QUARANTINED"),
        ("external_id", ""),
    ],
)
def test_one_shot_collection_rejects_nodes_outside_ready_open_scope(ready_node, field, value):
    from apps.subscriptions.metering import collect_node_once
    from common.errors import DomainError

    setattr(ready_node, field, value)
    ready_node.save(update_fields=[field, "updated_at"])

    with pytest.raises(DomainError) as error:
        collect_node_once(ready_node.pk, fetcher=lambda _node: {})

    assert error.value.code == "NODE_NOT_COLLECTABLE"


@pytest.mark.django_db
def test_one_shot_collection_command_requires_node_uuid_and_sanitizes_failures(
    ready_node, monkeypatch
):
    from apps.subscriptions.management.commands import refresh_node_usage

    ready_node.external_id = "target-instance"
    ready_node.save(update_fields=["external_id", "updated_at"])
    output = io.StringIO()
    monkeypatch.setattr(refresh_node_usage, "collect_node_once", lambda *_args: 1)

    call_command("refresh_node_usage", "--node-id", str(ready_node.pk), stdout=output)

    assert output.getvalue().strip() == f"node={ready_node.pk} profiles_collected=1"
    with pytest.raises(CommandError, match="the following arguments are required: --node-id"):
        call_command("refresh_node_usage", stdout=io.StringIO())


@pytest.mark.django_db
def test_one_shot_collection_command_does_not_emit_fetcher_exception(ready_node, monkeypatch):
    from apps.subscriptions.management.commands import refresh_node_usage

    monkeypatch.setattr(
        refresh_node_usage,
        "collect_node_once",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("credential-fixture")),
    )

    with pytest.raises(CommandError, match="USAGE_COLLECTION_FAILED") as error:
        call_command("refresh_node_usage", "--node-id", str(ready_node.pk), stdout=io.StringIO())

    assert "credential-fixture" not in str(error.value)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "enabled,last_scheduled_at,expected_collections",
    [
        (False, None, 0),
        (True, "2026-11-06T00:55:00+00:00", 0),
        (True, "2026-11-06T00:40:00+00:00", 1),
        (True, None, 1),
    ],
)
def test_periodic_usage_collection_obeys_enabled_interval_and_due_time(
    ready_node, monkeypatch, enabled, last_scheduled_at, expected_collections
):
    from datetime import UTC, datetime

    from django.utils.dateparse import parse_datetime

    from apps.identity.models import NodeAutomationSetting
    from apps.subscriptions import tasks

    ready_node.external_id = "ready-instance"
    ready_node.save(update_fields=["external_id", "updated_at"])
    NodeAutomationSetting.objects.create(
        usage_sync_enabled=enabled,
        usage_sync_interval_minutes=10,
        usage_sync_last_scheduled_at=(
            parse_datetime(last_scheduled_at) if last_scheduled_at else None
        ),
    )
    monkeypatch.setattr(
        tasks.timezone,
        "now",
        lambda: datetime(2026, 11, 6, 1, 0, tzinfo=UTC),
    )
    collected = []
    monkeypatch.setattr(tasks, "enforce_limits", lambda: [])
    monkeypatch.setattr(
        "apps.subscriptions.metering.collect_node",
        lambda node: collected.append(node.pk),
    )

    result = tasks.refresh_usage_and_limits()

    assert len(collected) == expected_collections
    assert result["collected"] == expected_collections
    setting = NodeAutomationSetting.objects.get(singleton_key=1)
    if enabled and expected_collections:
        assert setting.usage_sync_last_scheduled_at == datetime(2026, 11, 6, 1, 0, tzinfo=UTC)


@pytest.mark.django_db
def test_periodic_usage_collection_keeps_legacy_enabled_default(ready_node, monkeypatch):
    from datetime import UTC, datetime

    from apps.identity.models import NodeAutomationSetting
    from apps.subscriptions import tasks

    ready_node.external_id = "ready-instance"
    ready_node.save(update_fields=["external_id", "updated_at"])
    monkeypatch.setattr(
        tasks.timezone,
        "now",
        lambda: datetime(2026, 11, 6, 1, 0, tzinfo=UTC),
    )
    collected = []
    monkeypatch.setattr(tasks, "enforce_limits", lambda: [])
    monkeypatch.setattr(
        "apps.subscriptions.metering.collect_node",
        lambda node: collected.append(node.pk),
    )

    result = tasks.refresh_usage_and_limits()

    assert collected == [ready_node.pk]
    assert result["collected"] == 1
    assert NodeAutomationSetting.objects.get(singleton_key=1).usage_sync_enabled is True
