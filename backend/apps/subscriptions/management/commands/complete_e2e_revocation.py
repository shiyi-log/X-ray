from __future__ import annotations

from uuid import UUID

from django.core.management import BaseCommand, CommandError
from django.db import transaction

from apps.identity.management.commands.seed_e2e import assert_safe_test_database
from apps.operations.models import Operation


class Command(BaseCommand):
    help = "Finish one browser-test revocation with an explicit partial result."

    def add_arguments(self, parser):
        parser.add_argument("--operation-id", required=True)

    def handle(self, *args, **options):
        assert_safe_test_database()
        try:
            operation_id = UUID(options["operation_id"])
        except ValueError as exc:
            raise CommandError("operation id must be a UUID") from exc
        with transaction.atomic():
            try:
                operation = Operation.objects.select_for_update().get(pk=operation_id)
            except Operation.DoesNotExist as exc:
                raise CommandError("operation not found") from exc
            if operation.kind != "subscription.revoke":
                raise CommandError("operation is not a subscription revocation")
            operation.status = "PARTIALLY_SUCCEEDED"
            operation.current_step = "complete"
            operation.can_cancel = False
            operation.error_code = "REVOCATION_UNCONFIRMED"
            operation.result = {
                "node_states": [
                    {
                        "node_id": "44444444-4444-4444-8444-444444444444",
                        "status": "REVOCATION_UNCONFIRMED",
                        "last_error_code": "E2E_ISOLATION_UNCONFIRMED",
                    }
                ]
            }
            operation.save(
                update_fields=[
                    "status",
                    "current_step",
                    "can_cancel",
                    "error_code",
                    "result",
                    "updated_at",
                ]
            )
        self.stdout.write(self.style.SUCCESS(f"completed {operation_id} as partial"))
