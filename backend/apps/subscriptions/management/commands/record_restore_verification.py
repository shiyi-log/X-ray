from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.audit.services import AuditService
from apps.subscriptions.security_barrier import SecurityBarrier
from apps.subscriptions.security_events import SecurityLedger


class Command(BaseCommand):
    help = "Record independently verified recovery evidence without opening the barrier."

    def add_arguments(self, parser):
        parser.add_argument("--proof", required=True)
        parser.add_argument("--authorization-reference", required=True)
        parser.add_argument("--confirm", required=True)

    def handle(self, *args, **options):
        if options["confirm"] != "RECORD VERIFIED RECOVERY":
            raise CommandError("exact restore verification confirmation is required")
        authorization = options["authorization_reference"].strip()
        if len(authorization) < 8:
            raise CommandError("a concrete authorization reference is required")
        if SecurityBarrier.state().mode != "MAINTENANCE":
            raise CommandError("restore verification requires maintenance mode")
        try:
            proof = json.loads(Path(options["proof"]).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CommandError("restore proof is unavailable or invalid") from exc
        required_true = {
            "tokens_reconciled",
            "credentials_rotated",
            "audit_caught_up",
            "old_credentials_rejected",
        }
        evidence = proof.get("evidence_refs") if isinstance(proof, dict) else None
        if (
            not isinstance(proof, dict)
            or any(proof.get(key) is not True for key in required_true)
            or not isinstance(evidence, list)
            or not evidence
            or any(not isinstance(value, str) or not value.strip() for value in evidence)
        ):
            raise CommandError("restore proof is incomplete; barrier remains closed")
        event = SecurityLedger.append(
            kind="RESTORE_VERIFIED",
            payload={
                **{key: True for key in sorted(required_true)},
                "evidence_refs": [value.strip()[:200] for value in evidence],
                "approval_reference": authorization,
            },
        )
        AuditService.append(
            action="recovery.verification_recorded",
            target_type="system",
            target_id=event["event_id"],
            result="MAINTENANCE",
            metadata={
                "approval_reference": authorization,
                "security_sequence": event["sequence"],
                "evidence_count": len(evidence),
            },
        )
        self.stdout.write(
            self.style.WARNING(
                f"verification recorded at sequence={event['sequence']}; "
                "dispatch and independently reconcile the ledger before reopening"
            )
        )
