from __future__ import annotations

import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import AuditService
from apps.identity.models import SuperAdmin
from apps.identity.services import revoke_all


class Command(BaseCommand):
    help = "Reset the local administrator TOTP secret and revoke all sessions."

    def handle(self, *args, **options):
        try:
            admin = SuperAdmin.objects.get(singleton_key=1)
        except SuperAdmin.DoesNotExist as exc:
            raise CommandError("no super administrator exists") from exc
        confirmation = input("Type RESET-TOTP to continue: ").strip()
        if confirmation != "RESET-TOTP":
            raise CommandError("confirmation did not match")
        password = getpass.getpass("Administrator password: ")
        if not admin.check_password(password):
            raise CommandError("password verification failed")
        with transaction.atomic():
            admin.totp_secret_envelope = None
            admin.totp_confirmed_at = None
            admin.recovery_code_hashes = []
            admin.last_totp_step = -1
            admin.save(
                update_fields=[
                    "totp_secret_envelope",
                    "totp_confirmed_at",
                    "recovery_code_hashes",
                    "last_totp_step",
                    "updated_at",
                ]
            )
            revoke_all(admin)
            AuditService.append(
                action="identity.reset_totp",
                target_type="SuperAdmin",
                target_id=admin.pk,
                result="SUCCEEDED",
                metadata={"source": "local_recovery_command", "at": timezone.now().isoformat()},
            )
        self.stdout.write(self.style.SUCCESS("TOTP reset and all sessions revoked"))
