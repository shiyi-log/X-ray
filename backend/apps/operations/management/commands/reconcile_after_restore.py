from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.audit.services import AuditService
from apps.nodes.models import ManagedNode
from apps.operations.models import Operation, OutboxEvent
from apps.subscriptions.security_barrier import SecurityBarrier


class Command(BaseCommand):
    help = "Fence restored workers, lock nodes, and optionally import security evidence."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", required=True)
        parser.add_argument("--events")
        parser.add_argument("--expected-sequence", type=int)

    def handle(self, *args, **options):
        if options["confirm"] != "LOCK RESTORED SYSTEM":
            raise CommandError("exact recovery confirmation is required")
        if bool(options["events"]) != bool(options["expected_sequence"]):
            raise CommandError("events and expected-sequence must be supplied together")

        SecurityBarrier.enter_restore()
        now = timezone.now()
        with transaction.atomic():
            node_count = ManagedNode.objects.exclude(desired_state="DELETED").update(
                security_state="MAINTENANCE",
                updated_at=now,
            )
            operation_count = Operation.objects.exclude(
                status__in=Operation.TERMINAL_STATUSES
            ).update(
                status="NEEDS_RECONCILIATION",
                lease_owner="",
                lease_expires_at=None,
                lease_fence=F("lease_fence") + 1,
                error_code="RESTORE_RECONCILIATION_REQUIRED",
                updated_at=now,
            )
            outbox_count = OutboxEvent.objects.filter(delivered_at__isnull=True).update(
                delivered_at=now,
                last_error_code="RESTORE_RECONCILIATION_REQUIRED",
            )
            AuditService.append(
                action="recovery.lockdown",
                target_type="system",
                result="MAINTENANCE",
                metadata={
                    "nodes_locked": node_count,
                    "operations_fenced": operation_count,
                    "outbox_suppressed": outbox_count,
                },
            )

        if options["events"]:
            try:
                document = json.loads(
                    Path(options["events"]).read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise CommandError("security event copy is unavailable or invalid") from exc
            events = document.get("events") if isinstance(document, dict) else None
            if not isinstance(events, list) or not SecurityBarrier.import_events(
                events,
                expected_sequence=options["expected_sequence"],
            ):
                raise CommandError("security event import failed; barrier remains closed")

        self.stdout.write(
            self.style.SUCCESS(
                "restored system locked: subscriptions and cloud writes remain unavailable"
            )
        )
