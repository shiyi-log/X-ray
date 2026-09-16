from __future__ import annotations

import hashlib
import json

import pytest
from django.core.management import call_command


def _chain_event(previous: str, **values) -> dict:
    event = {"previous_digest": previous, **values}
    event["digest"] = hashlib.sha256(
        json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return event


@pytest.mark.django_db
def test_external_revocation_tombstone_wins_over_active_row_from_old_backup():
    from apps.subscriptions.models import AccessProfile, RevocationTombstone
    from apps.subscriptions.security_barrier import SecurityBarrier
    from apps.subscriptions.tokens import TokenGone, TokenService

    profile = AccessProfile.objects.create(name="restored-old-profile")
    issued = TokenService.issue(profile.pk)
    digest = hashlib.sha256(issued.raw_token.encode("ascii")).hexdigest()
    first = _chain_event(
        "0" * 64,
        sequence=1,
        event_id="revoked-after-backup",
        kind="TOKEN_REVOKED",
        verified=True,
        token_digest=digest,
        reason="forced-revocation",
    )
    final = _chain_event(
        first["digest"],
        sequence=2,
        event_id="restore-proof",
        kind="RESTORE_VERIFIED",
        verified=True,
        tokens_reconciled=True,
        credentials_rotated=True,
        audit_caught_up=True,
        old_credentials_rejected=True,
    )

    SecurityBarrier.enter_restore()
    assert SecurityBarrier.reconcile([first, final], expected_sequence=2) is True
    assert RevocationTombstone.objects.filter(token_digest=digest).exists()
    with pytest.raises(TokenGone):
        TokenService.resolve(issued.raw_token)


@pytest.mark.django_db
def test_tampered_independent_security_chain_never_opens_barrier():
    from apps.subscriptions.models import SecurityState
    from apps.subscriptions.security_barrier import SecurityBarrier

    first = _chain_event(
        "0" * 64,
        sequence=1,
        event_id="first",
        kind="TOKEN_RECONCILED",
        verified=True,
    )
    final = _chain_event(
        first["digest"],
        sequence=2,
        event_id="final",
        kind="RESTORE_VERIFIED",
        verified=True,
        tokens_reconciled=True,
        credentials_rotated=True,
        audit_caught_up=True,
        old_credentials_rejected=True,
    )
    final["old_credentials_rejected"] = False

    SecurityBarrier.enter_restore()
    assert SecurityBarrier.reconcile([first, final], expected_sequence=2) is False
    assert SecurityState.objects.get(singleton_key=1).mode == "MAINTENANCE"


@pytest.mark.django_db
def test_restore_import_never_opens_even_when_copy_contains_final_proof():
    from apps.subscriptions.models import SecurityState
    from apps.subscriptions.security_barrier import SecurityBarrier

    final = _chain_event(
        "0" * 64,
        sequence=1,
        event_id="proof-must-not-auto-open",
        kind="RESTORE_VERIFIED",
        verified=True,
        tokens_reconciled=True,
        credentials_rotated=True,
        audit_caught_up=True,
        old_credentials_rejected=True,
    )
    SecurityBarrier.enter_restore()
    assert SecurityBarrier.import_events([final], expected_sequence=1) is True
    assert SecurityState.objects.get(singleton_key=1).mode == "MAINTENANCE"


@pytest.mark.django_db(transaction=True)
def test_token_revocation_reaches_append_only_external_ledger_without_raw_token(tmp_path):
    from apps.subscriptions.models import (
        AccessProfile,
        RevocationTombstone,
        SecurityEventOutbox,
        SecurityState,
    )
    from apps.subscriptions.tokens import TokenService

    profile = AccessProfile.objects.create(name="external-ledger-profile")
    issued = TokenService.issue(profile.pk)
    digest = hashlib.sha256(issued.raw_token.encode("ascii")).hexdigest()
    TokenService.disable(issued.subscription_id)

    assert RevocationTombstone.objects.filter(token_digest=digest).exists()
    assert SecurityEventOutbox.objects.filter(delivered_at__isnull=True).count() == 1
    assert SecurityState.objects.get(singleton_key=1).security_backup_lagging is True

    ledger_dir = tmp_path / "ledger"
    call_command("dispatch_security_events", "--directory", str(ledger_dir))
    state = SecurityState.objects.get(singleton_key=1)
    assert state.security_backup_lagging is False
    assert state.last_external_security_sequence == state.last_security_sequence == 1
    event_files = list(ledger_dir.glob("*.json"))
    assert len(event_files) == 1
    persisted = event_files[0].read_text(encoding="utf-8")
    assert digest in persisted
    assert issued.raw_token not in persisted

    snapshot = tmp_path / "snapshot.json"
    call_command("export_security_events", "--output", str(snapshot))
    document = json.loads(snapshot.read_text(encoding="utf-8"))
    assert document["expected_sequence"] == 1
    assert document["events"][0]["token_digest"] == digest
