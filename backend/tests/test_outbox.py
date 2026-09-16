from uuid import uuid4

import pytest
from django.utils import timezone


@pytest.mark.django_db
def test_broker_failure_keeps_outbox_pending_and_retry_delivers(admin):
    from apps.operations.models import OutboxEvent
    from apps.operations.outbox import dispatch_pending
    from apps.operations.services import OperationService

    operation = OperationService.submit(
        kind="node.inspect",
        target_id=uuid4(),
        params={},
        key=uuid4(),
        preview_id=None,
        admin=admin,
    )

    def unavailable(*_args):
        raise ConnectionError("broker unavailable")

    assert dispatch_pending(unavailable) == 0
    event = OutboxEvent.objects.get(operation=operation)
    assert event.delivered_at is None
    assert event.attempts == 1
    assert event.last_error_code == "BROKER_UNAVAILABLE"

    OutboxEvent.objects.filter(pk=event.pk).update(available_at=timezone.now())
    published = []
    assert dispatch_pending(lambda *args: published.append(args)) == 1
    event.refresh_from_db()
    assert event.delivered_at is not None
    assert published == [(str(operation.pk), 1)]


@pytest.mark.django_db
def test_duplicate_delivery_does_not_duplicate_operation(admin):
    from apps.operations.services import OperationService

    key = uuid4()
    target_id = uuid4()
    kwargs = {
        "kind": "node.inspect",
        "target_id": target_id,
        "params": {},
        "key": key,
        "preview_id": None,
        "admin": admin,
    }
    first = OperationService.submit(**kwargs)
    second = OperationService.submit(**kwargs)
    assert first.pk == second.pk


@pytest.mark.django_db
def test_terminal_operation_redelivery_is_acknowledged_without_dispatch(admin, monkeypatch):
    from apps.operations.handlers import handle_operation
    from apps.operations.services import OperationService

    operation = OperationService.submit(
        kind="node.inspect",
        target_id=uuid4(),
        params={},
        key=uuid4(),
        preview_id=None,
        admin=admin,
    )
    operation.status = "SUCCEEDED"
    operation.save(update_fields=["status", "updated_at"])

    def forbidden_dispatch(*_args, **_kwargs):
        raise AssertionError("terminal operation was dispatched")

    monkeypatch.setattr(
        "apps.operations.handlers.NodeLifecycle.dispatch", forbidden_dispatch
    )
    assert handle_operation(str(operation.pk)) == {
        "operation_id": str(operation.pk),
        "status": "SUCCEEDED",
    }


@pytest.mark.django_db
def test_cancelling_operation_is_cancelled_without_dispatch(admin, monkeypatch):
    from apps.operations.handlers import handle_operation
    from apps.operations.services import OperationService

    operation = OperationService.submit(
        kind="node.stop",
        target_id=uuid4(),
        params={},
        key=uuid4(),
        preview_id=None,
        admin=admin,
    )
    operation.status = "CANCELLING"
    operation.save(update_fields=["status", "updated_at"])

    def forbidden_dispatch(*_args, **_kwargs):
        raise AssertionError("cancelled operation was dispatched")

    monkeypatch.setattr(
        "apps.operations.handlers.NodeLifecycle.dispatch", forbidden_dispatch
    )
    assert handle_operation(str(operation.pk))["status"] == "CANCELLED"
    operation.refresh_from_db()
    assert operation.status == "CANCELLED"
