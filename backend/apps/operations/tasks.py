from __future__ import annotations

from celery import shared_task


@shared_task(acks_late=True)
def execute_operation(operation_id: str, schema_version: int = 1):
    if schema_version != 1:
        raise ValueError("unsupported operation schema version")
    from .handlers import handle_operation

    return handle_operation(operation_id)
