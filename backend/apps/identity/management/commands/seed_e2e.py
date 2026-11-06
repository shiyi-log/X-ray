from __future__ import annotations

import hashlib
from uuid import UUID

from django.conf import settings
from django.core.management import BaseCommand, CommandError, call_command
from django.db import connection
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.identity.models import SuperAdmin
from apps.operations.models import Operation, OperationStep
from apps.subscriptions.models import (
    AccessProfile,
    SecurityState,
    Subscription,
    SubscriptionPool,
    SubscriptionRevision,
    SubscriptionToken,
)
from common.crypto import configured_secret_store

E2E_ADMIN = "e2e-owner"
E2E_PASSWORD = "e2e-only-password"
E2E_TOTP_SECRET = "JBSWY3DPEHPK3PXP"
FIXED_OPERATION_ID = UUID("11111111-1111-4111-8111-111111111111")
FIXED_TARGET_ID = UUID("22222222-2222-4222-8222-222222222222")
FIXED_TOKEN = "e2e_test_subscription_token_12345678901234"


def assert_safe_test_database() -> None:
    name = str(connection.settings_dict.get("NAME") or "")
    if getattr(settings, "XRAY_ENV", "") != "test" or name != "xray_test":
        raise CommandError("seed_e2e only runs with XRAY_ENV=test on xray_test")
    run_id = str(getattr(settings, "XRAY_E2E_RUN_ID", "") or "")
    try:
        if str(UUID(run_id)) != run_id:
            raise ValueError
    except ValueError as exc:
        raise CommandError("seed_e2e requires an isolated E2E database marker") from exc

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('xray.e2e_run_id', true)")
        marker = cursor.fetchone()
    if not marker or marker[0] != run_id:
        raise CommandError("seed_e2e requires an isolated E2E database marker")


class Command(BaseCommand):
    help = "Seed deterministic browser fixtures in the dedicated X-ray test database."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", required=True)

    def handle(self, *args, **options):
        assert_safe_test_database()
        call_command("flush", interactive=False, verbosity=0)
        SecurityState.objects.create(singleton_key=1, mode="OPEN")

        admin = SuperAdmin.objects.create_superuser(E2E_ADMIN, E2E_PASSWORD)
        admin.totp_secret_envelope = configured_secret_store().encrypt(
            E2E_TOTP_SECRET.encode(), purpose="control", aad=f"totp:{admin.pk}".encode()
        )
        admin.totp_confirmed_at = timezone.now()
        admin.last_totp_step = -1
        admin.save(
            update_fields=["totp_secret_envelope", "totp_confirmed_at", "last_totp_step"]
        )

        Operation.objects.create(
            id=FIXED_OPERATION_ID,
            admin=admin,
            kind="node.create",
            target_type="node",
            target_id=FIXED_TARGET_ID,
            params={"fixture": "e2e"},
            request_hash="1" * 64,
            idempotency_key=UUID("33333333-3333-4333-8333-333333333333"),
            status="RUNNING",
            current_step="cloud.create",
        )
        OperationStep.objects.create(
            operation_id=FIXED_OPERATION_ID,
            name="cloud.create",
            phase="cloud",
            status="RUNNING",
            attempt=1,
        )

        AccessProfile.objects.create(name="e2e-new-device")
        revoke_profile = AccessProfile.objects.create(name="e2e-revocation-device")
        token_digest = hashlib.sha256(FIXED_TOKEN.encode()).hexdigest()
        pool, _created = SubscriptionPool.objects.get_or_create(
            singleton_key=1,
            defaults={"name": "default"},
        )
        subscription = Subscription.objects.create(
            pool=pool,
            profile=revoke_profile,
            token_digest=token_digest,
            token_epoch=1,
            status="ACTIVE",
        )
        SubscriptionToken.objects.create(
            subscription=subscription,
            token_digest=token_digest,
            token_epoch=1,
            status="ACTIVE",
        )
        revision = SubscriptionRevision.objects.create(
            subscription=subscription,
            number=1,
            public_version="e2e-revision-1",
            payloads={"shadowrocket": "test-only-redacted", "clash": "test-only-redacted"},
            payload_hashes={"shadowrocket": "2" * 64, "clash": "3" * 64},
            node_versions={},
            usable=True,
        )
        subscription.current_revision = revision
        subscription.save(update_fields=["current_revision", "updated_at"])
        AuditEvent.objects.create(
            action="e2e.seed.complete",
            target_type="test_fixture",
            target_id=str(FIXED_OPERATION_ID),
            result="SUCCEEDED",
            actor=admin,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"seeded browser fixtures; operation={FIXED_OPERATION_ID}"
            )
        )
