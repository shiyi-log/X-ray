from __future__ import annotations

from django.db import transaction
from django.db.models import F
from django.utils.dateparse import parse_datetime

from .models import RevocationTombstone, SecurityEventRecord, SecurityState
from .security_events import DIGEST_PATTERN, FIXED_EVENT_FIELDS, events_are_complete


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
            state.security_backup_lagging = True
            state.save(
                update_fields=[
                    "mode",
                    "restore_epoch",
                    "security_backup_lagging",
                    "updated_at",
                ]
            )

    @classmethod
    def import_events(cls, events: list[dict], *, expected_sequence: int) -> bool:
        return cls._apply_events(
            events,
            expected_sequence=expected_sequence,
            allow_open=False,
        )

    @classmethod
    def reconcile(cls, events: list[dict], *, expected_sequence: int) -> bool:
        return cls._apply_events(
            events,
            expected_sequence=expected_sequence,
            allow_open=True,
        )

    @classmethod
    def _apply_events(
        cls,
        events: list[dict],
        *,
        expected_sequence: int,
        allow_open: bool,
    ) -> bool:
        with transaction.atomic():
            state, _created = SecurityState.objects.select_for_update().get_or_create(
                singleton_key=1,
                defaults={"mode": "MAINTENANCE"},
            )
            state.mode = "MAINTENANCE"
            state.expected_security_sequence = expected_sequence

            valid = events_are_complete(events, expected_sequence=expected_sequence)
            if valid:
                valid = cls._records_do_not_conflict(events)
            if valid:
                valid = cls._revocation_events_are_valid(events)
            if not valid:
                state.security_backup_lagging = True
                state.save(
                    update_fields=[
                        "mode",
                        "expected_security_sequence",
                        "security_backup_lagging",
                        "updated_at",
                    ]
                )
                return False

            for event in events:
                SecurityEventRecord.objects.get_or_create(
                    sequence=event["sequence"],
                    defaults={
                        "event_id": event["event_id"],
                        "previous_digest": event["previous_digest"],
                        "digest": event["digest"],
                        "kind": event["kind"],
                        "verified": event["verified"],
                        "payload": {
                            key: value
                            for key, value in event.items()
                            if key not in FIXED_EVENT_FIELDS
                        },
                        "restore_epoch": state.restore_epoch,
                    },
                )
                if event["kind"] == "TOKEN_REVOKED":
                    revoked_at = parse_datetime(str(event.get("occurred_at", "")))
                    defaults = {
                        "reason": str(event.get("reason", "external-revocation"))[:120],
                        "source_event_id": event["event_id"],
                        "source_sequence": event["sequence"],
                    }
                    if revoked_at is not None:
                        defaults["revoked_at"] = revoked_at
                    RevocationTombstone.objects.get_or_create(
                        token_digest=event["token_digest"],
                        defaults=defaults,
                    )

            state.last_security_sequence = expected_sequence
            state.last_external_security_sequence = expected_sequence
            state.security_backup_lagging = False
            can_open = allow_open and cls._final_event_allows_open(events[-1])
            state.mode = "OPEN" if can_open else "MAINTENANCE"
            state.save(
                update_fields=[
                    "mode",
                    "last_security_sequence",
                    "expected_security_sequence",
                    "last_external_security_sequence",
                    "security_backup_lagging",
                    "updated_at",
                ]
            )
            return can_open if allow_open else True

    @staticmethod
    def _records_do_not_conflict(events: list[dict]) -> bool:
        for event in events:
            existing = SecurityEventRecord.objects.filter(
                sequence=event["sequence"]
            ).first()
            event_id_match = SecurityEventRecord.objects.filter(
                event_id=event["event_id"]
            ).first()
            if existing and (
                existing.event_id != event["event_id"]
                or existing.previous_digest != event["previous_digest"]
                or existing.digest != event["digest"]
            ):
                return False
            if event_id_match and (
                event_id_match.sequence != event["sequence"]
                or event_id_match.digest != event["digest"]
            ):
                return False
        return True

    @staticmethod
    def _revocation_events_are_valid(events: list[dict]) -> bool:
        return all(
            event["kind"] != "TOKEN_REVOKED"
            or DIGEST_PATTERN.fullmatch(str(event.get("token_digest", "")))
            for event in events
        )

    @staticmethod
    def _final_event_allows_open(final: dict) -> bool:
        return bool(
            final["kind"] == "RESTORE_VERIFIED"
            and final.get("tokens_reconciled") is True
            and final.get("credentials_rotated") is True
            and final.get("audit_caught_up") is True
            and final.get("old_credentials_rejected") is True
        )
