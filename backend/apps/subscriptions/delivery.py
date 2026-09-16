from __future__ import annotations

from uuid import UUID

from .models import SecretDeliveryReceipt, Subscription
from .tokens import IssuedToken, TokenService


class DeliveryService:
    @staticmethod
    def _receipt(issued: IssuedToken, *, kind: str) -> IssuedToken:
        subscription = Subscription.objects.get(pk=issued.subscription_id)
        SecretDeliveryReceipt.objects.create(
            subscription=subscription,
            token_epoch=subscription.token_epoch,
            token_digest=subscription.token_digest,
            kind=kind,
        )
        return issued

    @classmethod
    def issue(cls, profile_id: UUID) -> IssuedToken:
        return cls._receipt(TokenService.issue(profile_id), kind="ISSUE")

    @classmethod
    def rotate(cls, subscription_id: UUID) -> IssuedToken:
        return cls._receipt(TokenService.rotate(subscription_id), kind="ROTATE")

    @staticmethod
    def retrieve(_receipt_id: UUID):
        raise LookupError("one-time secret is not recoverable")
