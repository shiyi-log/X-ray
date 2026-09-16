from __future__ import annotations

from django.db import DatabaseError
from django.http import HttpResponse
from django.views.decorators.http import require_http_methods

from common.crypto import configured_subscription_store

from .security_barrier import PublishingBlocked, SecurityBarrier
from .tokens import TokenGone, TokenService, TokenUnknown

UNAVAILABLE_BODY = b"subscription unavailable\n"


class RevisionUnavailable(Exception):
    pass


class PublicSubscriptionReader:
    @staticmethod
    def read(raw_token: str, *, format: str) -> bytes:
        subscription = TokenService.resolve(raw_token)
        SecurityBarrier.assert_open(purpose="public_read")
        revision = subscription.current_revision
        if revision is None or not revision.usable:
            raise RevisionUnavailable()
        envelope = revision.payloads.get(format)
        if envelope is None:
            raise RevisionUnavailable()
        aad = f"revision:{revision.pk}:{revision.number}:{format}".encode()
        return configured_subscription_store().decrypt(
            envelope,
            purpose="subscription.payload",
            aad=aad,
        )


def _response(body: bytes, *, status: int, content_type: str = "text/plain"):
    response = HttpResponse(body, status=status, content_type=content_type)
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_http_methods(["GET", "HEAD"])
def public_subscription(request, raw_token: str):
    requested_format = request.GET.get("format", "shadowrocket")
    try:
        body = PublicSubscriptionReader.read(raw_token, format=requested_format)
        status = 200
    except TokenGone:
        body, status = UNAVAILABLE_BODY, 410
    except TokenUnknown:
        body, status = UNAVAILABLE_BODY, 404
    except (PublishingBlocked, RevisionUnavailable, DatabaseError, ValueError, KeyError):
        body, status = UNAVAILABLE_BODY, 503
    if request.method == "HEAD":
        body = b""
    return _response(body, status=status)
