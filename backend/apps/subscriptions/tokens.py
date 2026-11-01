from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from common.errors import DomainError

from .models import (
    AccessProfile,
    RevocationTombstone,
    Subscription,
    SubscriptionPool,
    SubscriptionToken,
)
from .security_events import SecurityLedger

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


class TokenUnknown(Exception):
    def __init__(self):
        super().__init__("subscription unavailable")


class TokenGone(Exception):
    def __init__(self):
        super().__init__("subscription unavailable")


@dataclass(frozen=True, slots=True)
class IssuedToken:
    subscription_id: UUID
    raw_token: str


def _fresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode("ascii")).hexdigest()


def _digest(raw_token: str) -> str:
    if not isinstance(raw_token, str) or not TOKEN_PATTERN.fullmatch(raw_token):
        raise TokenUnknown()
    return hashlib.sha256(raw_token.encode("ascii")).hexdigest()


class TokenService:
    @staticmethod
    def _revoke_token_locked(token: SubscriptionToken, *, reason: str) -> SubscriptionToken:
        if token.status == "REVOKED":
            return token
        if token.status != "ACTIVE":
            raise DomainError("TOKEN_NOT_ACTIVE", "订阅令牌不是活动状态", status_code=409)
        token.revoked_at = timezone.now()
        token.status = "REVOKED"
        token.save(update_fields=["status", "revoked_at"])
        tombstone, created = RevocationTombstone.objects.get_or_create(
            token_digest=token.token_digest,
            defaults={"reason": reason, "revoked_at": token.revoked_at},
        )
        if created:
            event = SecurityLedger.append(
                kind="TOKEN_REVOKED",
                payload={"token_digest": token.token_digest, "reason": tombstone.reason},
            )
            RevocationTombstone.objects.filter(pk=tombstone.pk).update(
                source_event_id=event["event_id"],
                source_sequence=event["sequence"],
            )
        return token

    @staticmethod
    def issue(profile_id: UUID) -> IssuedToken:
        raw, digest = _fresh_token()
        try:
            with transaction.atomic():
                profile = AccessProfile.objects.select_for_update().get(pk=profile_id)
                if profile.status != "ACTIVE":
                    raise DomainError(
                        "PROFILE_NOT_ACTIVE", "访问身份不是活动状态", status_code=409
                    )
                if Subscription.objects.filter(profile=profile).exists():
                    raise DomainError(
                        "SECRET_ALREADY_DELIVERED",
                        "订阅令牌已交付；请显式轮换",
                        status_code=409,
                    )
                if RevocationTombstone.objects.filter(token_digest=digest).exists():
                    raise DomainError(
                        "SECRET_ALREADY_DELIVERED",
                        "订阅令牌未交付；请重新发起创建",
                        status_code=409,
                    )
                pool, _created = SubscriptionPool.objects.get_or_create(
                    singleton_key=1,
                    defaults={"name": "default"},
                )
                subscription = Subscription.objects.create(
                    pool=pool,
                    profile=profile,
                    token_digest=digest,
                    token_epoch=1,
                    status="ACTIVE",
                )
                SubscriptionToken.objects.create(
                    subscription=subscription,
                    token_digest=digest,
                    token_epoch=1,
                    status="ACTIVE",
                )
                return IssuedToken(subscription.pk, raw)
        except IntegrityError as exc:
            raise DomainError(
                "SECRET_ALREADY_DELIVERED",
                "订阅令牌未交付；请重新发起创建",
                status_code=409,
            ) from exc

    @staticmethod
    def rotate(subscription_id: UUID) -> IssuedToken:
        raw, digest = _fresh_token()
        with transaction.atomic():
            subscription = (
                Subscription.objects.select_for_update()
                .select_related("profile")
                .get(pk=subscription_id)
            )
            profile = AccessProfile.objects.select_for_update().get(
                pk=subscription.profile_id
            )
            if profile.status != "ACTIVE" or subscription.status != "ACTIVE":
                raise DomainError(
                    "PROFILE_NOT_ACTIVE", "访问身份不是活动状态", status_code=409
                )
            if RevocationTombstone.objects.filter(token_digest=digest).exists():
                raise DomainError(
                    "SECRET_ALREADY_DELIVERED",
                    "订阅令牌未交付；请重新发起轮换",
                    status_code=409,
                )
            current = SubscriptionToken.objects.select_for_update().get(
                subscription=subscription,
                token_epoch=subscription.token_epoch,
            )
            new_epoch = subscription.token_epoch + 1
            replacement = SubscriptionToken.objects.create(
                subscription=subscription,
                token_digest=digest,
                token_epoch=new_epoch,
                status="ACTIVE",
            )
            if current.status != "REVOKED":
                current.status = "REVOKED"
                current.revoked_at = timezone.now()
            current.replaced_by = replacement
            current.save(update_fields=["status", "revoked_at", "replaced_by"])
            revoked_at = current.revoked_at or timezone.now()
            tombstone, created = RevocationTombstone.objects.get_or_create(
                token_digest=current.token_digest,
                defaults={"reason": "token-rotated", "revoked_at": revoked_at},
            )
            if current.revoked_at != tombstone.revoked_at:
                current.revoked_at = tombstone.revoked_at
                current.save(update_fields=["revoked_at"])
            if created:
                event = SecurityLedger.append(
                    kind="TOKEN_REVOKED",
                    payload={
                        "token_digest": current.token_digest,
                        "reason": tombstone.reason,
                    },
                )
                RevocationTombstone.objects.filter(pk=tombstone.pk).update(
                    source_event_id=event["event_id"],
                    source_sequence=event["sequence"],
                )
            subscription.token_digest = digest
            subscription.token_epoch = new_epoch
            subscription.save(update_fields=["token_digest", "token_epoch", "updated_at"])
            return IssuedToken(subscription.pk, raw)

    @staticmethod
    def disable(subscription_id: UUID) -> None:
        with transaction.atomic():
            subscription = Subscription.objects.select_for_update().get(pk=subscription_id)
            if subscription.status == "REVOKED":
                return
            token = SubscriptionToken.objects.select_for_update().get(
                subscription=subscription,
                token_epoch=subscription.token_epoch,
            )
            TokenService._revoke_token_locked(token, reason="subscription-disabled")
            subscription.status = "REVOKED"
            subscription.save(update_fields=["status", "updated_at"])

    @staticmethod
    def revoke_token(subscription_id: UUID, token_id: UUID) -> SubscriptionToken:
        with transaction.atomic():
            Subscription.objects.select_for_update().get(pk=subscription_id)
            token = (
                SubscriptionToken.objects.select_for_update()
                .get(pk=token_id, subscription_id=subscription_id)
            )
            return TokenService._revoke_token_locked(token, reason="token-revoked")

    @staticmethod
    def resolve(raw_token: str) -> Subscription:
        digest = _digest(raw_token)
        if RevocationTombstone.objects.filter(token_digest=digest).exists():
            raise TokenGone()
        token = SubscriptionToken.objects.filter(token_digest=digest).first()
        subscription = (
            Subscription.objects.select_related("profile", "current_revision")
            .filter(token_digest=digest)
            .first()
        )
        if token is None:
            if subscription is None:
                raise TokenUnknown()
            raise TokenGone()
        if token.status != "ACTIVE":
            raise TokenGone()
        if subscription is not None:
            if (
                token.subscription_id != subscription.pk
                or token.token_epoch != subscription.token_epoch
                or subscription.status != "ACTIVE"
                or subscription.profile.status != "ACTIVE"
            ):
                raise TokenGone()
            return subscription
        raise TokenGone()
