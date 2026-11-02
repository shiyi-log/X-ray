from __future__ import annotations

from uuid import UUID

from django.db import transaction

from apps.nodes.lifecycle import NodeLifecycle
from common.errors import DomainError

from .models import Operation


def handle_operation(operation_id: str, *, revocation_service=None):
    with transaction.atomic():
        operation = Operation.objects.select_for_update().get(pk=UUID(operation_id))
        if operation.status in Operation.TERMINAL_STATUSES:
            return {"operation_id": str(operation.pk), "status": operation.status}
        if operation.status == "CANCELLING":
            operation.status = "CANCELLED"
            operation.lease_owner = ""
            operation.lease_expires_at = None
            operation.save(
                update_fields=[
                    "status",
                    "lease_owner",
                    "lease_expires_at",
                    "updated_at",
                ]
            )
            return {"operation_id": str(operation.pk), "status": operation.status}
    if operation.kind == "subscription.revoke":
        if revocation_service is None:
            from apps.subscriptions.revocation import RevocationService

            revocation_service = RevocationService()
        revocation_service.run(operation.pk)
        operation.refresh_from_db()
        return {"operation_id": str(operation.pk), "status": operation.status}
    if operation.kind == "node.access_sync":
        from apps.subscriptions.access import AccessService

        AccessService.sync(operation.pk)
        operation.refresh_from_db()
        return {"operation_id": str(operation.pk), "status": operation.status}
    if not operation.kind.startswith("node."):
        raise DomainError("OPERATION_KIND_UNSUPPORTED", "不支持的操作类型", status_code=400)
    action = operation.kind.removeprefix("node.")
    NodeLifecycle().dispatch(action, operation.target_id, operation_id=operation.pk)
    operation.refresh_from_db()
    return {"operation_id": str(operation.pk), "status": operation.status}
