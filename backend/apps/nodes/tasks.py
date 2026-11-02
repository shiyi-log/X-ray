from __future__ import annotations

from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from celery import shared_task
from django.db import transaction
from django.utils import timezone


@shared_task
def schedule_node_status_refreshes():
    """Queue due read-only refreshes, leaving provider calls to the worker."""
    from apps.identity.models import NodeStatusSyncSetting, SuperAdmin
    from apps.nodes.models import ManagedNode
    from apps.operations.models import Operation
    from apps.operations.services import OperationService

    scheduled = 0
    skipped = 0
    with transaction.atomic():
        setting = (
            NodeStatusSyncSetting.objects.select_for_update()
            .filter(singleton_key=1)
            .first()
        )
        if setting is None or not setting.enabled:
            return {"scheduled": 0, "skipped": 0, "disabled": True}

        now = timezone.now()
        if setting.last_scheduled_at is not None:
            due_at = setting.last_scheduled_at + timedelta(minutes=setting.interval_minutes)
            if now < due_at:
                return {"scheduled": 0, "skipped": 0, "due_at": due_at.isoformat()}

        admin = SuperAdmin.objects.filter(singleton_key=1, is_active=True).first()
        if admin is None:
            return {"scheduled": 0, "skipped": 0, "admin_unavailable": True}

        nodes = (
            ManagedNode.objects.select_for_update()
            .filter(external_id__gt="")
            .exclude(desired_state="DELETED")
            .order_by("pk")
        )
        for node in nodes:
            in_flight = Operation.objects.filter(
                kind="node.refresh",
                target_id=node.pk,
            ).exclude(status__in=Operation.TERMINAL_STATUSES)
            if in_flight.exists():
                skipped += 1
                continue

            OperationService.submit(
                kind="node.refresh",
                target_id=node.pk,
                params={
                    "region": node.region,
                    "account_id": str(node.cloud_account_id),
                },
                key=uuid5(
                    NAMESPACE_URL,
                    f"xray-node-refresh:{setting.pk}:{node.pk}:{now.isoformat()}",
                ),
                preview_id=None,
                admin=admin,
                cloud_credential_version=node.cloud_credential_version,
            )
            scheduled += 1

        setting.last_scheduled_at = now
        setting.save(update_fields=["last_scheduled_at", "updated_at"])

    return {"scheduled": scheduled, "skipped": skipped, "at": now.isoformat()}
