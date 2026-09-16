from __future__ import annotations

from uuid import UUID

from django.http import JsonResponse

from common.admin_api import admin_endpoint, json_payload, paginated_response

from .delivery import DeliveryService
from .models import AccessProfile, Subscription
from .publishing import Publisher
from .revocation import RevocationService
from .serializers import profile_representation, subscription_representation


def _uuid(value, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a UUID") from exc


def _secret_response(issued, request) -> JsonResponse:
    base = request.build_absolute_uri("/").rstrip("/")
    return JsonResponse(
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


@admin_endpoint("GET", "POST")
def profile_collection(request):
    if request.method == "GET":
        values = AccessProfile.objects.select_related("subscription").order_by("name", "pk")
        return paginated_response(request, values, profile_representation)
    payload = json_payload(request)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    profile = AccessProfile.objects.create(name=name)
    return JsonResponse(profile_representation(profile), status=201)


@admin_endpoint("GET")
def profile_detail(request, profile_id):
    profile = AccessProfile.objects.select_related("subscription").get(pk=profile_id)
    return JsonResponse(profile_representation(profile))


@admin_endpoint("POST", recent=True)
def issue(request, profile_id):
    return _secret_response(DeliveryService.issue(profile_id), request)


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
    return paginated_response(request, values, subscription_representation)


@admin_endpoint("POST", recent=True)
def rotate(request, subscription_id):
    return _secret_response(DeliveryService.rotate(subscription_id), request)


@admin_endpoint("POST")
def publish(request, subscription_id):
    revision = Publisher.publish(subscription_id)
    subscription = Subscription.objects.select_related("profile", "current_revision").get(
        pk=subscription_id
    )
    value = subscription_representation(subscription)
    value["published_revision"] = revision.number
    return JsonResponse(value)
