from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.subscriptions.security_barrier import SecurityBarrier


class Command(BaseCommand):
    help = "Reconcile an independent security-event copy before reopening recovery."

    def add_arguments(self, parser):
        parser.add_argument("--events", required=True)
        parser.add_argument("--expected-sequence", required=True, type=int)

    def handle(self, *args, **options):
        SecurityBarrier.enter_restore()
        path = Path(options["events"])
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CommandError("security event copy is unavailable or invalid") from exc
        events = document.get("events") if isinstance(document, dict) else None
        if not isinstance(events, list):
            raise CommandError("security event copy must contain an events list")
        if not SecurityBarrier.reconcile(
            events,
            expected_sequence=options["expected_sequence"],
        ):
            raise CommandError("security reconciliation is incomplete; barrier remains closed")
        self.stdout.write(
            self.style.SUCCESS(
                f"security barrier opened at sequence={options['expected_sequence']}"
            )
        )
