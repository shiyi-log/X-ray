import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connections


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


@pytest.mark.django_db
def test_periodic_usage_retries_only_failed_node_before_next_full_interval(
    ready_node, monkeypatch
):
    from datetime import UTC, datetime, timedelta

    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.quota import reserve_node
    from apps.subscriptions import tasks

    ready_node.external_id = "ready-instance"
    ready_node.save(update_fields=["external_id", "updated_at"])
    successful = reserve_node(
        ready_node.pool_id,
        account_id=ready_node.cloud_account_id,
        region=ready_node.region,
        plan_id=ready_node.plan_id,
        image_id=ready_node.image_id,
        operation_key=uuid4(),
    )
    successful.external_id = "successful-instance"
    successful.provisioning_state = "READY"
    successful.save(update_fields=["external_id", "provisioning_state", "updated_at"])
    NodeAutomationSetting.objects.create(
        usage_sync_enabled=True, usage_sync_interval_minutes=10
    )
    now = datetime(2026, 11, 6, 1, 0, tzinfo=UTC)
    monkeypatch.setattr(tasks.timezone, "now", lambda: now)
    calls = []
    failed_once = False
    monkeypatch.setattr(tasks, "enforce_limits", lambda: [])

    def collect(node):
        nonlocal failed_once
        calls.append(node.pk)
        if node.pk == ready_node.pk and not failed_once:
            failed_once = True
            raise RuntimeError("temporary collector outage")

    monkeypatch.setattr("apps.subscriptions.metering.collect_node", collect)
    first = tasks.refresh_usage_and_limits()

    assert first["unavailable"] == 1
    assert set(calls) == {ready_node.pk, successful.pk}
    ready_node.refresh_from_db()
    successful.refresh_from_db()
    assert ready_node.usage_sync_retry_count == 1
    assert ready_node.usage_sync_retry_at == now + timedelta(minutes=1)
    assert successful.usage_sync_retry_at is None

    calls.clear()
    monkeypatch.setattr(tasks.timezone, "now", lambda: now + timedelta(minutes=1))
    from apps.nodes.models import ManagedNode

    assert ManagedNode.objects.filter(
        pk=ready_node.pk, usage_sync_retry_at__lte=now + timedelta(minutes=1)
    ).exists()
    retry = tasks.refresh_usage_and_limits()

    assert retry["collected"] == 1
    assert retry["unavailable"] == 0
    assert calls == [ready_node.pk]
    ready_node.refresh_from_db()
    assert ready_node.usage_sync_retry_count == 0
    assert ready_node.usage_sync_retry_at is None


@pytest.mark.django_db
def test_periodic_usage_does_not_retry_when_sync_is_disabled(ready_node, monkeypatch):
    from datetime import UTC, datetime

    from apps.identity.models import NodeAutomationSetting
    from apps.subscriptions import tasks

    ready_node.usage_sync_retry_count = 1
    ready_node.usage_sync_retry_at = datetime(2026, 11, 6, 0, 59, tzinfo=UTC)
    ready_node.save(update_fields=["usage_sync_retry_count", "usage_sync_retry_at", "updated_at"])
    NodeAutomationSetting.objects.create(
        usage_sync_enabled=False,
        usage_sync_interval_minutes=10,
        usage_sync_last_scheduled_at=datetime(2026, 11, 6, 0, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(
        tasks.timezone,
        "now",
        lambda: datetime(2026, 11, 6, 1, 0, tzinfo=UTC),
    )
    calls = []
    monkeypatch.setattr(tasks, "enforce_limits", lambda: [])
    monkeypatch.setattr(
        "apps.subscriptions.metering.collect_node",
        lambda node: calls.append(node.pk),
    )

    result = tasks.refresh_usage_and_limits()

    assert result["collected"] == 0
    assert calls == []
    ready_node.refresh_from_db()
    assert ready_node.usage_sync_retry_count == 1
    assert ready_node.usage_sync_retry_at == datetime(2026, 11, 6, 0, 59, tzinfo=UTC)


@pytest.mark.django_db
@pytest.mark.parametrize("minutes_after_retry_due,expected_calls", [(0, 1), (-1, 0)])
def test_periodic_usage_retry_uses_inclusive_due_boundary(
    ready_node, monkeypatch, minutes_after_retry_due, expected_calls
):
    from datetime import UTC, datetime, timedelta

    from apps.identity.models import NodeAutomationSetting
    from apps.subscriptions import tasks

    ready_node.external_id = "ready-instance"
    ready_node.save(update_fields=["external_id", "updated_at"])
    retry_at = datetime(2026, 11, 6, 1, 0, tzinfo=UTC)
    ready_node.usage_sync_retry_count = 1
    ready_node.usage_sync_retry_at = retry_at
    ready_node.save(update_fields=["usage_sync_retry_count", "usage_sync_retry_at", "updated_at"])
    NodeAutomationSetting.objects.create(
        usage_sync_enabled=True,
        usage_sync_interval_minutes=10,
        usage_sync_last_scheduled_at=retry_at,
    )
    monkeypatch.setattr(
        tasks.timezone,
        "now",
        lambda: retry_at + timedelta(minutes=minutes_after_retry_due),
    )
    calls = []
    monkeypatch.setattr(tasks, "enforce_limits", lambda: [])
    monkeypatch.setattr(
        "apps.subscriptions.metering.collect_node", lambda node: calls.append(node.pk)
    )

    result = tasks.refresh_usage_and_limits()

    assert len(calls) == expected_calls
    assert result["collected"] == expected_calls


@pytest.mark.django_db
def test_periodic_usage_backoff_caps_at_sixty_minutes(ready_node, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from apps.identity.models import NodeAutomationSetting
    from apps.subscriptions import tasks

    ready_node.external_id = "ready-instance"
    ready_node.save(update_fields=["external_id", "updated_at"])
    NodeAutomationSetting.objects.create(usage_sync_enabled=True, usage_sync_interval_minutes=1440)
    start = datetime(2026, 11, 6, 1, 0, tzinfo=UTC)
    monkeypatch.setattr(tasks, "enforce_limits", lambda: [])
    monkeypatch.setattr(
        "apps.subscriptions.metering.collect_node",
        lambda _node: (_ for _ in ()).throw(RuntimeError("temporary outage")),
    )

    now = start
    for attempt in range(1, 9):
        monkeypatch.setattr(tasks.timezone, "now", lambda now=now: now)
        result = tasks.refresh_usage_and_limits()
        assert result["unavailable"] == 1
        ready_node.refresh_from_db()
        assert ready_node.usage_sync_retry_count == min(attempt, 7)
        assert ready_node.usage_sync_retry_at == now + timedelta(
            minutes=min(2 ** (min(attempt, 7) - 1), 60)
        )
        now = ready_node.usage_sync_retry_at


@pytest.mark.django_db
def test_periodic_usage_reclaims_expired_collection_lease_before_full_interval(
    ready_node, monkeypatch
):
    from datetime import UTC, datetime, timedelta

    from apps.identity.models import NodeAutomationSetting
    from apps.subscriptions import tasks

    ready_node.external_id = "ready-instance"
    ready_node.save(update_fields=["external_id", "updated_at"])
    now = datetime(2026, 11, 6, 1, 0, tzinfo=UTC)
    ready_node.usage_sync_lease_id = uuid4()
    ready_node.usage_sync_lease_expires_at = now
    ready_node.save(
        update_fields=[
            "usage_sync_lease_id",
            "usage_sync_lease_expires_at",
            "updated_at",
        ]
    )
    NodeAutomationSetting.objects.create(
        usage_sync_enabled=True,
        usage_sync_interval_minutes=60,
        usage_sync_last_scheduled_at=now - timedelta(minutes=1),
    )
    monkeypatch.setattr(tasks.timezone, "now", lambda: now)
    calls = []
    monkeypatch.setattr(tasks, "enforce_limits", lambda: [])
    monkeypatch.setattr(
        "apps.subscriptions.metering.collect_node", lambda node: calls.append(node.pk)
    )

    result = tasks.refresh_usage_and_limits()

    assert calls == [ready_node.pk]
    assert result["collected"] == 1
    ready_node.refresh_from_db()
    assert ready_node.usage_sync_lease_id is None
    assert ready_node.usage_sync_lease_expires_at is None


@pytest.mark.django_db
def test_periodic_usage_stale_worker_cannot_clear_replacement_lease(ready_node, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from apps.identity.models import NodeAutomationSetting
    from apps.subscriptions import tasks

    ready_node.external_id = "ready-instance"
    ready_node.save(update_fields=["external_id", "updated_at"])
    now = datetime(2026, 11, 6, 1, 0, tzinfo=UTC)
    replacement_lease = uuid4()
    NodeAutomationSetting.objects.create(usage_sync_enabled=True)
    monkeypatch.setattr(tasks.timezone, "now", lambda: now)
    monkeypatch.setattr(tasks, "enforce_limits", lambda: [])

    def collect(_node):
        from apps.nodes.models import ManagedNode

        ManagedNode.objects.filter(pk=ready_node.pk).update(
            usage_sync_lease_id=replacement_lease,
            usage_sync_lease_expires_at=now + timedelta(minutes=tasks.USAGE_SYNC_LEASE_MINUTES),
            usage_sync_retry_count=4,
        )

    monkeypatch.setattr("apps.subscriptions.metering.collect_node", collect)
    result = tasks.refresh_usage_and_limits()

    assert result["collected"] == 1
    ready_node.refresh_from_db()
    assert ready_node.usage_sync_lease_id == replacement_lease
    assert ready_node.usage_sync_retry_count == 4


@pytest.mark.django_db
def test_periodic_usage_sets_retry_delay_from_collection_failure_time(ready_node, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from apps.identity.models import NodeAutomationSetting
    from apps.subscriptions import tasks

    ready_node.external_id = "ready-instance"
    ready_node.save(update_fields=["external_id", "updated_at"])
    started_at = datetime(2026, 11, 6, 1, 0, tzinfo=UTC)
    failed_at = started_at + timedelta(minutes=3)
    NodeAutomationSetting.objects.create(usage_sync_enabled=True)
    clock = [started_at]
    monkeypatch.setattr(tasks.timezone, "now", lambda: clock[0])
    monkeypatch.setattr(tasks, "enforce_limits", lambda: [])

    def collect(_node):
        clock[0] = failed_at
        raise RuntimeError("temporary outage")

    monkeypatch.setattr("apps.subscriptions.metering.collect_node", collect)
    result = tasks.refresh_usage_and_limits()

    assert result["unavailable"] == 1
    ready_node.refresh_from_db()
    assert ready_node.usage_sync_retry_at == failed_at + timedelta(minutes=1)
    assert ready_node.usage_sync_lease_expires_at is None


@pytest.mark.django_db
def test_periodic_usage_skips_node_with_active_collection_lease(ready_node, monkeypatch):
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from apps.identity.models import NodeAutomationSetting
    from apps.subscriptions import tasks

    now = datetime(2026, 11, 6, 1, 0, tzinfo=UTC)
    lease_id = uuid4()
    ready_node.usage_sync_lease_id = lease_id
    ready_node.usage_sync_lease_expires_at = now + timedelta(minutes=1)
    ready_node.save(
        update_fields=[
            "usage_sync_lease_id",
            "usage_sync_lease_expires_at",
            "updated_at",
        ]
    )
    NodeAutomationSetting.objects.create(usage_sync_enabled=True)
    monkeypatch.setattr(tasks.timezone, "now", lambda: now)
    calls = []
    monkeypatch.setattr(tasks, "enforce_limits", lambda: [])
    monkeypatch.setattr(
        "apps.subscriptions.metering.collect_node", lambda node: calls.append(node.pk)
    )

    result = tasks.refresh_usage_and_limits()

    assert calls == []
    assert result["collected"] == 0
    ready_node.refresh_from_db()
    assert ready_node.usage_sync_lease_id == lease_id


@pytest.mark.django_db(transaction=True)
def test_concurrent_usage_workers_claim_node_lease_once(ready_node):
    from datetime import UTC, datetime

    from apps.subscriptions.tasks import _claim_usage_sync_node

    ready_node.external_id = "ready-instance"
    ready_node.save(update_fields=["external_id", "updated_at"])
    now = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)
    barrier = Barrier(2)

    def claim():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            result = _claim_usage_sync_node(ready_node.pk, now, retry_only=False)
            return result[0] if result else None
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _worker: claim(), range(2)))

    winners = [lease_id for lease_id in claims if lease_id is not None]
    assert len(winners) == 1
    ready_node.refresh_from_db()
    assert ready_node.usage_sync_lease_id == winners[0]
    assert ready_node.usage_sync_lease_expires_at == datetime(
        2026, 11, 11, 9, 5, tzinfo=UTC
    )
