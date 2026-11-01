from __future__ import annotations

from uuid import UUID

from django.db import transaction

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
    def issue(cls, profile_id: UUID, *, admin=None) -> IssuedToken:
        with transaction.atomic():
            issued = TokenService.issue(profile_id)
            if admin is not None:
                # A newly delivered subscription includes every currently publishable
                # profile-scoped protocol. Explicit assignment remains available for
                # legacy callers, but the subscription UI no longer needs it.
                from .access import AccessService

                AccessService.assign(profile_id, protocol_ids=None, admin=admin)
            return cls._receipt(issued, kind="ISSUE")

    @classmethod
    def rotate(cls, subscription_id: UUID) -> IssuedToken:
        return cls._receipt(TokenService.rotate(subscription_id), kind="ROTATE")

    @staticmethod
    def retrieve(_receipt_id: UUID):
        raise LookupError("one-time secret is not recoverable")
