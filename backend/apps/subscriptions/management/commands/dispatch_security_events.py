from __future__ import annotations

import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.subscriptions.security_events import dispatch_security_events


class Command(BaseCommand):
    help = "Append pending security events to the independent ledger directory."

    def add_arguments(self, parser):
        parser.add_argument("--directory")
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        configured = options["directory"] or os.getenv("XRAY_SECURITY_LEDGER_DIR")
        if not configured:
            raise CommandError("security ledger directory is required")
        directory = Path(configured)
        if not directory.is_absolute():
            raise CommandError("security ledger directory must be absolute")
        if options["limit"] < 1 or options["limit"] > 1000:
            raise CommandError("limit must be between 1 and 1000")
        try:
            count = dispatch_security_events(directory, limit=options["limit"])
        except (OSError, RuntimeError, ValueError) as exc:
            raise CommandError("security ledger append failed; backup is lagging") from exc
        self.stdout.write(f"dispatched={count}")
