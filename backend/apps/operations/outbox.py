from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import OutboxEvent


def dispatch_pending(publisher, *, limit: int = 100) -> int:
    """Publish pending operation IDs and mark delivery only after broker ack."""
    delivered = 0
    while delivered < limit:
        with transaction.atomic():
            event = (
                OutboxEvent.objects.select_for_update(skip_locked=True)
                .filter(delivered_at__isnull=True, available_at__lte=timezone.now())
                .order_by("created_at")
                .first()
            )
            if event is None:
                break
            event.attempts += 1
            try:
                publisher(str(event.operation_id), event.schema_version)
            except Exception:
                event.last_error_code = "BROKER_UNAVAILABLE"
                delay = min(60, 2 ** min(event.attempts, 5))
                event.available_at = timezone.now() + timedelta(seconds=delay)
                event.save(
                    update_fields=[
                        "attempts",
                        "last_error_code",
                        "available_at",
                    ]
                )
                break
            event.delivered_at = timezone.now()
            event.last_error_code = ""
            event.save(
                update_fields=[
                    "attempts",
                    "delivered_at",
                    "last_error_code",
                ]
            )
            delivered += 1
    return delivered
