from uuid import uuid4

import pytest
from django.utils import timezone


def test_shared_operation_task_uses_project_celery_broker():
    from django.conf import settings

    from apps.operations.tasks import execute_operation

    assert execute_operation.app.main == "xray_manager"
    assert execute_operation.app.conf.broker_url == settings.CELERY_BROKER_URL


def test_dispatch_command_publishes_through_project_celery_app(monkeypatch):
    from apps.operations.management.commands import dispatch_outbox
    from apps.operations.tasks import execute_operation
    from config.celery import app as project_app

    operation_id = str(uuid4())
    schema_version = 7
    published = []

    class TaskProxy:
        name = execute_operation.name

        @staticmethod
        def delay(*_args, **_kwargs):
            raise AssertionError("dispatcher used the task's implicit current app")

    def dispatch_pending(publisher):
        publisher(operation_id, schema_version)
        return 1

    def send_task(task_name, *, args):
        published.append((task_name, args))

    monkeypatch.setattr(dispatch_outbox, "dispatch_pending", dispatch_pending)
    monkeypatch.setattr(dispatch_outbox, "execute_operation", TaskProxy())
    monkeypatch.setattr(project_app, "send_task", send_task)

    dispatch_outbox.Command().handle()

    assert published == [(execute_operation.name, (operation_id, schema_version))]


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
