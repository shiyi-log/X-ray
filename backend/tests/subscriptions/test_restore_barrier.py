import json

import pytest
from django.core.management import CommandError, call_command


def restore_events():
    from apps.subscriptions.security_events import event_digest

    first = {
        "sequence": 1,
        "event_id": "event-1",
        "previous_digest": "0" * 64,
        "kind": "TOKEN_RECONCILED",
        "verified": True,
    }
    first["digest"] = event_digest(first)
    final = {
        "sequence": 2,
        "event_id": "event-2",
        "previous_digest": first["digest"],
        "kind": "RESTORE_VERIFIED",
        "verified": True,
        "tokens_reconciled": True,
        "credentials_rotated": True,
        "audit_caught_up": True,
        "old_credentials_rejected": True,
    }
    final["digest"] = event_digest(final)
    return [first, final]


@pytest.mark.django_db
def test_restore_stays_closed_on_gap_or_missing_rotation_proof():
    from apps.subscriptions.security_barrier import PublishingBlocked, SecurityBarrier

    SecurityBarrier.enter_restore()
    events = restore_events()
    assert SecurityBarrier.reconcile([events[1]], expected_sequence=2) is False
    with pytest.raises(PublishingBlocked):
        SecurityBarrier.assert_open(purpose="public_read")

    incomplete = restore_events()
    incomplete[-1]["credentials_rotated"] = False
    from apps.subscriptions.security_events import event_digest

    incomplete[-1]["digest"] = event_digest(incomplete[-1])
    assert SecurityBarrier.reconcile(incomplete, expected_sequence=2) is False
    with pytest.raises(PublishingBlocked):
        SecurityBarrier.assert_open(purpose="cloud_write")


@pytest.mark.django_db
def test_complete_contiguous_security_events_reopen_barrier_idempotently():
    from apps.subscriptions.models import SecurityEventRecord, SecurityState
    from apps.subscriptions.security_barrier import SecurityBarrier

    SecurityBarrier.enter_restore()
    events = restore_events()
    assert SecurityBarrier.reconcile(events, expected_sequence=2) is True
    SecurityBarrier.assert_open(purpose="public_read")
    SecurityBarrier.assert_open(purpose="cloud_write")
    assert SecurityEventRecord.objects.count() == 2
    assert SecurityBarrier.reconcile(events, expected_sequence=2) is True
    assert SecurityEventRecord.objects.count() == 2
    state = SecurityState.objects.get(singleton_key=1)
    assert state.mode == "OPEN"
    assert state.last_security_sequence == 2


@pytest.mark.django_db
def test_replay_with_changed_digest_relocks_barrier():
    from apps.subscriptions.security_barrier import PublishingBlocked, SecurityBarrier

    SecurityBarrier.enter_restore()
    events = restore_events()
    assert SecurityBarrier.reconcile(events, expected_sequence=2) is True
    changed = restore_events()
    changed[0]["digest"] = "c" * 64
    assert SecurityBarrier.reconcile(changed, expected_sequence=2) is False
    with pytest.raises(PublishingBlocked):
        SecurityBarrier.assert_open(purpose="reopen_node")


@pytest.mark.django_db
def test_malformed_security_event_structure_fails_closed():
    from apps.subscriptions.models import SecurityState
    from apps.subscriptions.security_barrier import SecurityBarrier

    SecurityBarrier.enter_restore()
    assert SecurityBarrier.reconcile([None], expected_sequence=1) is False
    assert SecurityState.objects.get(singleton_key=1).mode == "MAINTENANCE"


@pytest.mark.django_db
def test_reconcile_command_imports_a_complete_independent_event_copy(tmp_path):
    from apps.subscriptions.models import SecurityState
    from apps.subscriptions.security_barrier import SecurityBarrier

    SecurityBarrier.enter_restore()
    event_file = tmp_path / "security-events.json"
    event_file.write_text(json.dumps({"events": restore_events()}), encoding="utf-8")

    call_command(
        "reconcile_security_state",
        "--events",
        str(event_file),
        "--expected-sequence",
        "2",
    )

    state = SecurityState.objects.get(singleton_key=1)
    assert state.mode == "OPEN"
    assert state.last_security_sequence == 2


@pytest.mark.django_db
def test_reconcile_command_failure_keeps_the_restore_barrier_closed(tmp_path):
    from apps.subscriptions.models import SecurityState
    from apps.subscriptions.security_barrier import SecurityBarrier

    SecurityBarrier.enter_restore()
    with pytest.raises(CommandError):
        call_command(
            "reconcile_security_state",
            "--events",
            str(tmp_path / "missing.json"),
            "--expected-sequence",
            "2",
        )
    assert SecurityState.objects.get(singleton_key=1).mode == "MAINTENANCE"
