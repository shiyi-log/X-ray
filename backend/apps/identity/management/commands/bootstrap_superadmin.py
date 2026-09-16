from __future__ import annotations

import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from apps.identity.models import SuperAdmin


class Command(BaseCommand):
    help = "Interactively create the single X-ray super administrator."

    def handle(self, *args, **options):
        if SuperAdmin.objects.exists():
            raise CommandError("a super administrator already exists")
        username = input("Username: ").strip()
        if not username:
            raise CommandError("username is required")
        password = getpass.getpass("Password (not echoed): ")
        confirm = getpass.getpass("Repeat password: ")
        if len(password) < 12 or password != confirm:
            raise CommandError("passwords must match and contain at least 12 characters")
        try:
            with transaction.atomic():
                SuperAdmin.objects.create_superuser(username, password)
        except IntegrityError as exc:
            raise CommandError("another administrator was created concurrently") from exc
        self.stdout.write(self.style.SUCCESS("super administrator created"))
