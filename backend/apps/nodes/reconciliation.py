from __future__ import annotations

from uuid import UUID

from .lifecycle import NodeLifecycle


def reconcile_node(
    node_id: UUID,
    *,
    operation_id: UUID,
    lifecycle: NodeLifecycle | None = None,
) -> None:
    (lifecycle or NodeLifecycle()).reconcile(node_id, operation_id=operation_id)
