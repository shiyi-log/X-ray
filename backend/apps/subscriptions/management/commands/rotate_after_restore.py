from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import AuditService
from apps.nodes.models import ManagedNode
from apps.subscriptions.models import AccessProfile, NodeCredential, Subscription
from apps.subscriptions.security_barrier import SecurityBarrier
from apps.subscriptions.tokens import TokenService


class Command(BaseCommand):
    help = "Invalidate restored identities after explicit recovery authorization."

    def add_arguments(self, parser):
        parser.add_argument("--authorization-reference", required=True)
        parser.add_argument("--confirm", required=True)

    def handle(self, *args, **options):
        if options["confirm"] != "INVALIDATE ALL RESTORED CREDENTIALS":
            raise CommandError("exact credential invalidation confirmation is required")
        authorization = options["authorization_reference"].strip()
        if len(authorization) < 8:
            raise CommandError("a concrete authorization reference is required")
        if SecurityBarrier.state().mode != "MAINTENANCE":
            raise CommandError("credential invalidation is restricted to recovery maintenance")

        now = timezone.now()
        with transaction.atomic():
            subscriptions = list(
                Subscription.objects.select_for_update().filter(status="ACTIVE")
            )
            for subscription in subscriptions:
                TokenService.disable(subscription.pk)
            profile_count = AccessProfile.objects.exclude(status="REVOKED").update(
                status="REVOKED",
                publishing_frozen=True,
                revoked_at=now,
                updated_at=now,
            )
            credential_count = NodeCredential.objects.filter(
                revoked_at__isnull=True
            ).update(revoked_at=now)
            node_count = ManagedNode.objects.exclude(desired_state="DELETED").update(
                security_state="MAINTENANCE",
                updated_at=now,
            )
            AuditService.append(
                action="recovery.credentials_invalidated",
                target_type="system",
                result="MAINTENANCE",
                metadata={
                    "approval_reference": authorization,
                    "subscriptions_invalidated": len(subscriptions),
                    "profiles_invalidated": profile_count,
                    "node_credentials_invalidated": credential_count,
                    "nodes_held": node_count,
                },
            )
        self.stdout.write(
            self.style.WARNING(
                "restored credentials invalidated; barrier remains closed until externally "
                "verified replacement credentials and a RESTORE_VERIFIED event are reconciled"
            )
        )
