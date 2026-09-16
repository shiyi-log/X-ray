from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from .models import SecurityEventOutbox, SecurityEventRecord, SecurityState

DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GENESIS_DIGEST = "0" * 64
FIXED_EVENT_FIELDS = {
    "sequence",
    "event_id",
    "previous_digest",
    "digest",
    "kind",
    "verified",
}


def event_digest(event: dict) -> str:
    canonical = {key: value for key, value in event.items() if key != "digest"}
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def events_are_complete(events: list[dict], *, expected_sequence: int) -> bool:
    if expected_sequence < 1 or len(events) != expected_sequence:
        return False
    if any(not isinstance(event, dict) for event in events):
        return False
    if [event.get("sequence") for event in events] != list(
        range(1, expected_sequence + 1)
    ):
        return False

    previous = GENESIS_DIGEST
    for event in events:
        required = {
            "sequence",
            "event_id",
            "previous_digest",
            "digest",
            "kind",
            "verified",
        }
        if not required.issubset(event):
            return False
        if not isinstance(event["event_id"], str) or not event["event_id"]:
            return False
        if not isinstance(event["kind"], str) or not event["kind"]:
            return False
        if event["verified"] is not True:
            return False
        if event["previous_digest"] != previous:
            return False
        if not DIGEST_PATTERN.fullmatch(str(event["digest"])):
            return False
        if event_digest(event) != event["digest"]:
            return False
        previous = event["digest"]
    return True


def record_as_event(record: SecurityEventRecord) -> dict:
    event = {
        "sequence": record.sequence,
        "event_id": record.event_id,
        "previous_digest": record.previous_digest,
        "digest": record.digest,
        "kind": record.kind,
        "verified": record.verified,
    }
    event.update(record.payload)
    return event


class SecurityLedger:
    @classmethod
    def append(cls, *, kind: str, payload: dict | None = None) -> dict:
        payload = dict(payload or {})
        with transaction.atomic():
            state, _created = SecurityState.objects.select_for_update().get_or_create(
                singleton_key=1,
                defaults={"mode": "MAINTENANCE"},
            )
            sequence = state.last_security_sequence + 1
            if sequence == 1:
                previous_digest = GENESIS_DIGEST
            else:
                previous = SecurityEventRecord.objects.filter(
                    sequence=sequence - 1
                ).first()
                if previous is None:
                    raise RuntimeError("security event sequence is incomplete")
                previous_digest = previous.digest
            event = {
                "sequence": sequence,
                "event_id": str(uuid4()),
                "previous_digest": previous_digest,
                "kind": kind,
                "verified": True,
                "occurred_at": timezone.now().isoformat(),
                **payload,
            }
            event["digest"] = event_digest(event)
            record = SecurityEventRecord.objects.create(
                sequence=sequence,
                event_id=event["event_id"],
                previous_digest=previous_digest,
                digest=event["digest"],
                kind=kind,
                verified=True,
                payload={
                    key: value
                    for key, value in event.items()
                    if key not in FIXED_EVENT_FIELDS
                },
                restore_epoch=state.restore_epoch,
            )
            SecurityEventOutbox.objects.create(event=record, payload=event)
            state.last_security_sequence = sequence
            state.expected_security_sequence = sequence
            state.security_backup_lagging = True
            state.save(
                update_fields=[
                    "last_security_sequence",
                    "expected_security_sequence",
                    "security_backup_lagging",
                    "updated_at",
                ]
            )
            return event

    @staticmethod
    def snapshot() -> dict:
        events = [
            record_as_event(record)
            for record in SecurityEventRecord.objects.order_by("sequence")
        ]
        expected = events[-1]["sequence"] if events else 0
        if expected and not events_are_complete(events, expected_sequence=expected):
            raise RuntimeError("security event ledger is incomplete")
        return {"schema_version": 1, "expected_sequence": expected, "events": events}


def dispatch_security_events(directory: Path, *, limit: int = 100) -> int:
    directory = directory.resolve()
    if directory in {Path("/"), Path("/var"), Path("/var/lib")}:
        raise ValueError("security ledger directory is too broad")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    delivered = 0
    while delivered < limit:
        with transaction.atomic():
            outbox = (
                SecurityEventOutbox.objects.select_for_update(skip_locked=True)
                .filter(delivered_at__isnull=True, available_at__lte=timezone.now())
                .select_related("event")
                .order_by("event__sequence")
                .first()
            )
            if outbox is None:
                break
            filename = f"{outbox.event.sequence:020d}-{outbox.event.event_id}.json"
            target = directory / filename
            encoded = (
                json.dumps(outbox.payload, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            outbox.attempts += 1
            try:
                if target.exists():
                    if target.read_bytes() != encoded:
                        raise RuntimeError("external security event conflicts")
                else:
                    with target.open("xb") as handle:
                        os.chmod(target, 0o600)
                        handle.write(encoded)
                        handle.flush()
                        os.fsync(handle.fileno())
                    directory_fd = os.open(directory, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
            except Exception:
                outbox.last_error_code = "SECURITY_LEDGER_WRITE_FAILED"
                outbox.save(update_fields=["attempts", "last_error_code"])
                SecurityState.objects.filter(singleton_key=1).update(
                    security_backup_lagging=True
                )
                raise
            outbox.delivered_at = timezone.now()
            outbox.last_error_code = ""
            outbox.save(update_fields=["attempts", "delivered_at", "last_error_code"])
            has_pending = SecurityEventOutbox.objects.filter(
                delivered_at__isnull=True
            ).exclude(pk=outbox.pk).exists()
            SecurityState.objects.filter(singleton_key=1).update(
                last_external_security_sequence=outbox.event.sequence,
                security_backup_lagging=has_pending,
            )
            delivered += 1
    return delivered
