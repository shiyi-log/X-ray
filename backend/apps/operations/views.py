from __future__ import annotations

from uuid import UUID

from django.http import JsonResponse

from apps.nodes.models import ManagedNode
from apps.subscriptions.models import AccessProfile, NodeCredential
from common.admin_api import admin_endpoint, json_payload, paginated_response
from common.errors import DomainError

from .models import Operation
from .serializers import operation_representation, preview_representation
from .services import ActionPreviewService, OperationService


def _uuid(value, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a UUID") from exc


@admin_endpoint("GET")
def collection(request):
    values = Operation.objects.filter(admin=request.xray_admin).order_by("-created_at", "pk")
    if request.GET.get("status"):
        values = values.filter(status=request.GET["status"])
    return paginated_response(request, values, operation_representation)


@admin_endpoint("GET")
def detail(request, operation_id):
    operation = Operation.objects.prefetch_related("steps", "revocation_nodes").get(
        pk=operation_id, admin=request.xray_admin
    )
    return JsonResponse(operation_representation(operation, include_steps=True))


@admin_endpoint("POST")
def cancel(request, operation_id):
    operation = OperationService.cancel(operation_id, admin=request.xray_admin)
    return JsonResponse(operation_representation(operation), status=202)


@admin_endpoint("POST")
def retry(request, operation_id):
    operation = OperationService.retry(operation_id, admin=request.xray_admin)
    return JsonResponse(operation_representation(operation), status=202)


@admin_endpoint("POST", recent=True)
def preview(request):
    payload = json_payload(request)
    kind = str(payload.get("kind") or "")
    target_id = _uuid(payload.get("target_id"), "target_id")
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    if kind == "subscription.revoke":
        profile = AccessProfile.objects.select_related("subscription").get(pk=target_id)
        shared_scopes = list(
            NodeCredential.objects.filter(
                profile=profile,
                revoked_at__isnull=True,
                credential_scope="shared",
            ).values_list("node_id", "protocol_id")
        )
        shared_query = NodeCredential.objects.none()
        for node_id, protocol_id in shared_scopes:
            shared_query = shared_query | NodeCredential.objects.filter(
                node_id=node_id,
                protocol_id=protocol_id,
                profile__status="ACTIVE",
                revoked_at__isnull=True,
            )
        impacted = list(
            AccessProfile.objects.filter(
                node_credentials__in=shared_query.exclude(profile=profile)
            )
            .distinct()
            .order_by("name", "pk")
            .values_list("id", "name")
        )
        snapshot = {
            "profile_status": profile.status,
            "subscription_status": profile.subscription.status,
            "impacted_profiles": [
                {"id": str(profile_id), "name": name} for profile_id, name in impacted
            ],
        }
        phrase = "确认强制撤销"
    elif kind in {"node.reinstall", "node.quarantine"}:
        node = ManagedNode.objects.get(pk=target_id)
        snapshot = {
            "external_id": node.external_id,
            "desired_generation": node.desired_generation,
            "security_state": node.security_state,
        }
        phrase = "确认重装" if kind == "node.reinstall" else "确认隔离"
    else:
        raise DomainError("PREVIEW_KIND_UNSUPPORTED", "不支持的危险操作预览", status_code=400)
    value = ActionPreviewService.create(
        admin=request.xray_admin,
        kind=kind,
        target_id=target_id,
        params=params,
        snapshot=snapshot,
        required_phrase=phrase,
    )
    return JsonResponse(preview_representation(value), status=201)
