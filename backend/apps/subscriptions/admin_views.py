from __future__ import annotations

from urllib.parse import urlsplit
from uuid import UUID

from common.admin_api import admin_endpoint, json_payload, paginated_response
from common.errors import DomainError
from django.conf import settings
from django.db import transaction
from django.http import JsonResponse

from .delivery import DeliveryService
from .management_api import mutation
from .models import AccessProfile, Subscription
from .policy import update_policy
from .publishing import Publisher
from .revocation import RevocationService
from .serializers import profile_representation, subscription_representation


def _uuid(value, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a UUID") from exc


def _secret_response(issued, request) -> JsonResponse:
    base = getattr(settings, "XRAY_PUBLIC_SUBSCRIPTION_BASE_URL", "") or request.build_absolute_uri(
        "/"
    ).rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid public subscription base URL")
    base = base.rstrip("/")
    response = JsonResponse(
        {
            "subscription_id": str(issued.subscription_id),
            "token": issued.raw_token,
            "urls": {
                format_name: f"{base}/s/{issued.raw_token}?format={format_name}"
                for format_name in ("shadowrocket", "clash", "mihomo", "v2ray")
            },
            "display_once": True,
        },
        status=201,
    )
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response


def _deliver_once(request, scope, deliver):
    # Store only non-secret delivery metadata. A replay can never recover a token.
    issued = None

    def action():
        nonlocal issued
        issued = deliver()
        return {"subscription_id": str(issued.subscription_id)}

    with transaction.atomic():
        mutation(request, scope, {}, action)
        if issued is None:
            raise DomainError(
                "SECRET_ALREADY_DELIVERED", "已交付，请使用已保存链接或显式轮换", status_code=409
            )
        return _secret_response(issued, request)


@admin_endpoint("GET", "POST")
def profile_collection(request):
    if request.method == "GET":
        values = AccessProfile.objects.select_related("subscription").order_by("name", "pk")
        return paginated_response(request, values, profile_representation)
    payload = json_payload(request)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")

    def create():
        profile = AccessProfile(name=name)
        update_policy(profile, payload)
        return profile_representation(profile)

    return JsonResponse(mutation(request, "profile:create", payload, create), status=201)


@admin_endpoint("GET", "PATCH")
def profile_detail(request, profile_id):
    profile = AccessProfile.objects.select_related("subscription").get(pk=profile_id)
    if request.method == "PATCH":
        payload = json_payload(request)

        def save():
            locked = AccessProfile.objects.select_for_update().get(pk=profile_id)
            return profile_representation(update_policy(locked, payload))

        return JsonResponse(mutation(request, f"profile:{profile_id}", payload, save))
    return JsonResponse(profile_representation(profile))


@admin_endpoint("POST", recent=True)
def issue(request, profile_id):
    return _deliver_once(request, f"issue:{profile_id}", lambda: DeliveryService.issue(profile_id))


@admin_endpoint("POST", recent=True)
def force_revoke(request, profile_id):
    payload = json_payload(request)
    operation = RevocationService.request(
        profile_id,
        key=_uuid(request.headers.get("Idempotency-Key"), "Idempotency-Key"),
        preview_id=_uuid(payload.get("preview_id"), "preview_id"),
        confirmation=str(payload.get("confirmation") or ""),
        admin=request.xray_admin,
    )
    response = JsonResponse(
        {
            "operation_id": str(operation.pk),
            "status": operation.status,
            "target_type": operation.target_type,
            "target_id": str(operation.target_id),
            "link_revoked": True,
        },
        status=202,
    )
    response["Location"] = f"/api/v1/operations/{operation.pk}/"
    return response


@admin_endpoint("GET")
def subscription_collection(request):
    values = Subscription.objects.select_related("profile", "current_revision").order_by(
        "profile__name", "pk"
    )
    if query := request.GET.get("q", "").strip():
        values = values.filter(profile__name__icontains=query)
    return paginated_response(request, values, subscription_representation)


@admin_endpoint("POST", recent=True)
def rotate(request, subscription_id):
    return _deliver_once(
        request, f"rotate:{subscription_id}", lambda: DeliveryService.rotate(subscription_id)
    )


@admin_endpoint("POST")
def publish(request, subscription_id):
    def action():
        revision = Publisher.publish(subscription_id)
        return {"number": revision.number}

    published = mutation(request, f"publish:{subscription_id}", {}, action)
    subscription = Subscription.objects.select_related("profile", "current_revision").get(
        pk=subscription_id
    )
    value = subscription_representation(subscription)
    value["published_revision"] = published["number"]
    return JsonResponse(value)
