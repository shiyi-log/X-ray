from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone


@pytest.mark.django_db
def test_reconcile_after_restore_locks_nodes_and_invalidates_old_worker_leases():
    from uuid import uuid4

    from django.utils import timezone as django_timezone

    from apps.cloud_accounts.models import CloudAccount, CloudCredentialVersion
    from apps.identity.models import SuperAdmin
    from apps.nodes.models import NodePool
    from apps.nodes.quota import reserve_node
    from apps.operations.models import Operation
    from apps.operations.services import OperationService
    from apps.subscriptions.models import SecurityState

    admin = SuperAdmin.objects.create_superuser("restore-owner", "test-only-password")
    account = CloudAccount.objects.create(
        name="Restore Fake AWS",
        provider="aws_lightsail",
        external_account_id="restore-test-account",
        credential_version=1,
        validated_at=django_timezone.now(),
        last_validation_code="OK",
    )
    credential = CloudCredentialVersion.objects.create(
        account=account,
        version=1,
        encrypted_credentials={"test": "opaque"},
        identity_verified_at=django_timezone.now(),
    )
    pool = NodePool.objects.create(name="restore-pool", quota=1)
    key = uuid4()
    node = reserve_node(
        pool.pk,
        account_id=account.pk,
        region="us-east-1",
        plan_id="nano",
        image_id="debian-12",
        operation_key=key,
    )
    operation = OperationService.submit(
        kind="node.create",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(account.pk)},
        key=key,
        preview_id=None,
        admin=admin,
        cloud_credential_version=credential,
    )
    operation.status = "RUNNING"
    operation.lease_owner = "worker-before-restore"
    operation.lease_fence = 9
    operation.lease_expires_at = timezone.now() + timedelta(minutes=5)
    operation.save(
        update_fields=[
            "status",
            "lease_owner",
            "lease_fence",
            "lease_expires_at",
            "updated_at",
        ]
    )

    call_command("reconcile_after_restore", "--confirm", "LOCK RESTORED SYSTEM")

    node.refresh_from_db()
    operation = Operation.objects.get(pk=operation.pk)
    state = SecurityState.objects.get(singleton_key=1)
    assert state.mode == "MAINTENANCE"
    assert state.restore_epoch == 1
    assert node.security_state == "MAINTENANCE"
    assert operation.status == "NEEDS_RECONCILIATION"
    assert operation.lease_owner == ""
    assert operation.lease_expires_at is None
    assert operation.lease_fence == 10


@pytest.mark.django_db
def test_reconcile_after_restore_requires_exact_confirmation():
    from django.core.management import CommandError

    with pytest.raises(CommandError):
        call_command("reconcile_after_restore", "--confirm", "yes")


@pytest.mark.django_db
def test_rotate_after_restore_requires_approval_and_keeps_barrier_closed():
    from django.core.management import CommandError

    from apps.subscriptions.models import AccessProfile, RevocationTombstone, SecurityState
    from apps.subscriptions.security_barrier import SecurityBarrier
    from apps.subscriptions.tokens import TokenService

    profile = AccessProfile.objects.create(name="restored-rotation")
    issued = TokenService.issue(profile.pk)
    SecurityBarrier.enter_restore()

    with pytest.raises(CommandError):
        call_command(
            "rotate_after_restore",
            "--authorization-reference",
            "short",
            "--confirm",
            "INVALIDATE ALL RESTORED CREDENTIALS",
        )

    call_command(
        "rotate_after_restore",
        "--authorization-reference",
        "RECOVERY-APPROVAL-2026-09-17",
        "--confirm",
        "INVALIDATE ALL RESTORED CREDENTIALS",
    )
    assert SecurityState.objects.get(singleton_key=1).mode == "MAINTENANCE"
    assert RevocationTombstone.objects.count() == 1
    profile.refresh_from_db()
    assert profile.status == "REVOKED"
    assert issued.raw_token not in str(RevocationTombstone.objects.values().first())


@pytest.mark.django_db
def test_restore_verification_requires_complete_proof_and_does_not_auto_open(tmp_path):
    from django.core.management import CommandError

    from apps.subscriptions.models import SecurityEventRecord, SecurityState
    from apps.subscriptions.security_barrier import SecurityBarrier

    SecurityBarrier.enter_restore()
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(json.dumps({"tokens_reconciled": True}), encoding="utf-8")
    with pytest.raises(CommandError):
        call_command(
            "record_restore_verification",
            "--proof",
            str(incomplete),
            "--authorization-reference",
            "RECOVERY-APPROVAL-1",
            "--confirm",
            "RECORD VERIFIED RECOVERY",
        )

    complete = tmp_path / "complete.json"
    complete.write_text(
        json.dumps(
            {
                "tokens_reconciled": True,
                "credentials_rotated": True,
                "audit_caught_up": True,
                "old_credentials_rejected": True,
                "evidence_refs": ["probe:new-accepted", "probe:old-rejected"],
            }
        ),
        encoding="utf-8",
    )
    call_command(
        "record_restore_verification",
        "--proof",
        str(complete),
        "--authorization-reference",
        "RECOVERY-APPROVAL-1",
        "--confirm",
        "RECORD VERIFIED RECOVERY",
    )
    assert SecurityEventRecord.objects.get(sequence=1).kind == "RESTORE_VERIFIED"
    assert SecurityState.objects.get(singleton_key=1).mode == "MAINTENANCE"
