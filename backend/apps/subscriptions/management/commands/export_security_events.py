from __future__ import annotations

import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.subscriptions.models import SecurityEventOutbox, SecurityState
from apps.subscriptions.security_events import SecurityLedger


class Command(BaseCommand):
    help = "Export a verified security-event snapshot without raw subscription tokens."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        output = Path(options["output"])
        if not output.is_absolute():
            raise CommandError("output must be an absolute path")
        state = SecurityState.objects.filter(singleton_key=1).first()
        if state is None:
            raise CommandError("security state is unavailable")
        if (
            state.security_backup_lagging
            or state.last_external_security_sequence != state.last_security_sequence
            or SecurityEventOutbox.objects.filter(delivered_at__isnull=True).exists()
        ):
            raise CommandError("independent security ledger is not current")
        try:
            snapshot = SecurityLedger.snapshot()
            output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            encoded = (
                json.dumps(snapshot, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            with output.open("xb") as handle:
                os.chmod(output, 0o600)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        except (OSError, RuntimeError) as exc:
            raise CommandError("security ledger export failed") from exc
        self.stdout.write(f"expected_sequence={snapshot['expected_sequence']}")
