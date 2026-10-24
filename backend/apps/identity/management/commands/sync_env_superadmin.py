from __future__ import annotations

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from apps.identity.models import SuperAdmin
from apps.identity.services import revoke_all


class Command(BaseCommand):
    help = "Create or update the single local test administrator from environment values."

    def handle(self, *args, **options):
        if (
            os.getenv("DJANGO_SETTINGS_MODULE") != "config.settings.test"
            or getattr(settings, "XRAY_ENV", "") != "test"
        ):
            raise CommandError("sync_env_superadmin requires the isolated test settings")
        database_name = str(connection.settings_dict.get("NAME") or "")
        if database_name not in {"xray_test", "test_xray_test"}:
            raise CommandError("sync_env_superadmin requires the xray_test database")

        username = (os.getenv("XRAY_ADMIN_USERNAME") or "").strip()
        password = os.getenv("XRAY_ADMIN_PASSWORD") or ""
        if not username or not password:
            raise CommandError("XRAY_ADMIN_USERNAME and XRAY_ADMIN_PASSWORD are required")
        if len(password) < 12:
            raise CommandError("XRAY_ADMIN_PASSWORD must contain at least 12 characters")
        if len(username) > SuperAdmin._meta.get_field("username").max_length:
            raise CommandError("XRAY_ADMIN_USERNAME is too long")

        with transaction.atomic():
            admin = SuperAdmin.objects.select_for_update().first()
            if admin is None:
                admin = SuperAdmin.objects.create_superuser(username, password)
            else:
                username_changed = admin.username != username
                password_changed = not admin.check_password(password)
                flags_changed = not (
                    admin.is_active and admin.is_staff and admin.is_superuser
                )
                if username_changed or password_changed or flags_changed:
                    update_fields = ["username"] if username_changed else []
                    admin.username = username
                    if password_changed:
                        admin.set_password(password)
                        admin.last_password_change_at = timezone.now()
                        update_fields.extend(["password", "last_password_change_at"])
                    if flags_changed:
                        admin.is_active = True
                        admin.is_staff = True
                        admin.is_superuser = True
                        update_fields.extend(["is_active", "is_staff", "is_superuser"])
                    admin.save(update_fields=[*update_fields, "updated_at"])
                    revoke_all(admin)

        self.stdout.write(self.style.SUCCESS("local test administrator synchronized"))
