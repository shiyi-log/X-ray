from __future__ import annotations

import re

from django.db import transaction
from django.db.models import F

from .models import SecurityEventRecord, SecurityState

DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class PublishingBlocked(Exception):
    pass


class SecurityBarrier:
    PURPOSES = {"public_read", "cloud_write", "reopen_node"}

    @classmethod
    def state(cls) -> SecurityState:
        try:
            return SecurityState.objects.get(singleton_key=1)
        except SecurityState.DoesNotExist as exc:
            raise PublishingBlocked("security state is unavailable") from exc

    @classmethod
    def assert_open(cls, *, purpose: str) -> None:
        if purpose not in cls.PURPOSES:
            raise ValueError("unsupported security barrier purpose")
        if cls.state().mode != "OPEN":
            raise PublishingBlocked("security barrier is closed")

    @classmethod
    def enter_restore(cls) -> None:
        with transaction.atomic():
            state, _created = SecurityState.objects.select_for_update().get_or_create(
                singleton_key=1,
                defaults={"mode": "MAINTENANCE"},
            )
            state.mode = "MAINTENANCE"
            state.restore_epoch = F("restore_epoch") + 1
            state.save(update_fields=["mode", "restore_epoch", "updated_at"])

    @classmethod
    def reconcile(cls, events: list[dict], *, expected_sequence: int) -> bool:
        with transaction.atomic():
            state, _created = SecurityState.objects.select_for_update().get_or_create(
                singleton_key=1,
                defaults={"mode": "MAINTENANCE"},
            )
            state.mode = "MAINTENANCE"
            state.expected_security_sequence = expected_sequence

            valid = cls._events_are_complete(events, expected_sequence=expected_sequence)
            if valid:
                for event in events:
                    existing = SecurityEventRecord.objects.filter(
                        sequence=event["sequence"]
                    ).first()
                    event_id_match = SecurityEventRecord.objects.filter(
                        event_id=event["event_id"]
                    ).first()
                    if (
                        existing
                        and (
                            existing.event_id != event["event_id"]
                            or existing.digest != event["digest"]
                        )
                    ) or (
                        event_id_match
                        and (
                            event_id_match.sequence != event["sequence"]
                            or event_id_match.digest != event["digest"]
                        )
                    ):
                        valid = False
                        break

            if not valid:
                state.save(
                    update_fields=[
                        "mode",
                        "expected_security_sequence",
                        "updated_at",
                    ]
                )
                return False

            for event in events:
                SecurityEventRecord.objects.get_or_create(
                    sequence=event["sequence"],
                    defaults={
                        "event_id": event["event_id"],
                        "digest": event["digest"],
                        "kind": event["kind"],
                        "verified": event["verified"],
                        "payload": {
                            key: value
                            for key, value in event.items()
                            if key
                            not in {"sequence", "event_id", "digest", "kind", "verified"}
                        },
                        "restore_epoch": state.restore_epoch,
                    },
                )
            state.mode = "OPEN"
            state.last_security_sequence = expected_sequence
            state.save(
                update_fields=[
                    "mode",
                    "last_security_sequence",
                    "expected_security_sequence",
                    "updated_at",
                ]
            )
            return True

    @staticmethod
    def _events_are_complete(events: list[dict], *, expected_sequence: int) -> bool:
        if expected_sequence < 1 or len(events) != expected_sequence:
            return False
        if any(not isinstance(event, dict) for event in events):
            return False
        if [event.get("sequence") for event in events] != list(
            range(1, expected_sequence + 1)
        ):
            return False
        required = {"sequence", "event_id", "digest", "kind", "verified"}
        if any(
            not required.issubset(event)
            or not isinstance(event["event_id"], str)
            or not DIGEST_PATTERN.fullmatch(str(event["digest"]))
            or event["verified"] is not True
            for event in events
        ):
            return False
        final = events[-1]
        return bool(
            final["kind"] == "RESTORE_VERIFIED"
            and final.get("tokens_reconciled") is True
            and final.get("credentials_rotated") is True
        )
