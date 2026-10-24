from __future__ import annotations

from uuid import UUID

from django.db import transaction
from django.http import JsonResponse

from apps.operations.services import OperationService
from common.admin_api import admin_endpoint, json_payload, paginated_response
from common.errors import DomainError
from common.regions import normalize_region

from .models import ManagedNode, NodePool
from .quota import reserve_node, set_allocations, set_quota
from .serializers import node_pool_representation, node_representation


def _uuid(value, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a UUID") from exc


def _operation_response(operation) -> JsonResponse:
    response = JsonResponse(
        {
            "operation_id": str(operation.pk),
            "status": operation.status,
            "target_type": operation.target_type,
            "target_id": str(operation.target_id),
        },
        status=202,
    )
    response["Location"] = f"/api/v1/operations/{operation.pk}/"
    return response


@admin_endpoint("GET", "POST")
def pool_collection(request):
    if request.method == "GET":
        return paginated_response(
            request, NodePool.objects.order_by("name", "pk"), node_pool_representation
        )
    payload = json_payload(request)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    raw_allocations = payload.get("allocations")
    if raw_allocations is None:
        region = normalize_region(payload.get("region"))
        quota = int(payload.get("quota", 3))
        if quota < 1:
            raise ValueError("quota must be at least 1")
        allocations = [{"region": region, "quota": quota}]
    else:
        allocations = raw_allocations
    if not isinstance(allocations, list) or not allocations:
        raise ValueError("allocations must be a non-empty list")
    if any(not isinstance(item, dict) for item in allocations):
        raise ValueError("each allocation must be an object")
    if any(int(item.get("quota", 0)) < 1 for item in allocations):
        raise ValueError("allocation quota must be at least 1")
    # Validate and persist the allocation rows atomically so invalid input
    # cannot leave a partially created pool behind.
    with transaction.atomic():
        pool = NodePool.objects.create(
            name=name,
            region=normalize_region(allocations[0].get("region")),
            quota=sum(int(item.get("quota", 0)) for item in allocations),
            allow_create=bool(payload.get("allow_create", True)),
        )
        set_allocations(pool.pk, allocations)
    pool.refresh_from_db()
    return JsonResponse(node_pool_representation(pool), status=201)


@admin_endpoint("GET", "PATCH")
def pool_detail(request, pool_id):
    pool = NodePool.objects.get(pk=pool_id)
    if request.method == "GET":
        return JsonResponse(node_pool_representation(pool))
    payload = json_payload(request)
    unknown = set(payload) - {"name", "region", "quota", "allocations", "allow_create"}
    if unknown:
        raise ValueError(f"unsupported fields: {sorted(unknown)}")
    if "allocations" in payload:
        pool = set_allocations(pool.pk, payload["allocations"])
    elif "quota" in payload:
        pool = set_quota(pool.pk, int(payload["quota"]))
    if "name" in payload:
        name = str(payload["name"]).strip()
        if not name:
            raise ValueError("name cannot be empty")
        pool.name = name
    if "region" in payload and "allocations" not in payload:
        region = normalize_region(payload["region"])
        current = list(pool.region_allocations.all())
        if len(current) > 1:
            raise DomainError(
                "MULTI_REGION_ALLOCATION_REQUIRED",
                "多地区节点池必须通过 allocations 调整地区",
                status_code=400,
            )
        current_quota = current[0].quota if current else pool.quota
        if region != pool.region and pool.nodes.filter(consumes_quota=True).exists():
            raise DomainError(
                "POOL_REGION_IN_USE",
                "节点池已有占用中的节点，不能更改地区",
                status_code=409,
            )
        set_allocations(pool.pk, [{"region": region, "quota": current_quota}])
        pool.refresh_from_db()
    if "allow_create" in payload:
        if not isinstance(payload["allow_create"], bool):
            raise ValueError("allow_create must be boolean")
        pool.allow_create = payload["allow_create"]
    pool.save(update_fields=["name", "region", "allow_create", "updated_at"])
    pool.refresh_from_db()
    return JsonResponse(node_pool_representation(pool))


@admin_endpoint("GET", "POST")
def node_collection(request):
    if request.method == "GET":
        nodes = ManagedNode.objects.select_related("pool", "cloud_account").order_by(
            "-created_at", "pk"
        )
        if request.GET.get("pool_id"):
            nodes = nodes.filter(pool_id=request.GET["pool_id"])
        if request.GET.get("security_state"):
            nodes = nodes.filter(security_state=request.GET["security_state"])
        return paginated_response(request, nodes, node_representation)

    payload = json_payload(request)
    key = _uuid(request.headers.get("Idempotency-Key"), "Idempotency-Key")
    required = ("pool_id", "account_id", "plan_id", "image_id")
    if any(not payload.get(field) for field in required):
        raise ValueError(f"required fields: {', '.join(required)}")
    with transaction.atomic():
        pool = NodePool.objects.get(pk=_uuid(payload["pool_id"], "pool_id"))
        requested_region = payload.get("region")
        if requested_region is None or not str(requested_region).strip():
            allocations = list(pool.region_allocations.all())
            if len(allocations) <= 1:
                requested_region = pool.region
            else:
                requested_region = None
        node = reserve_node(
            _uuid(payload["pool_id"], "pool_id"),
            account_id=_uuid(payload["account_id"], "account_id"),
            region=requested_region,
            plan_id=str(payload["plan_id"]),
            image_id=str(payload["image_id"]),
            operation_key=key,
        )
        operation = OperationService.submit(
            kind="node.create",
            target_id=node.pk,
            params={
                "region": node.region,
                "account_id": str(node.cloud_account_id),
            },
            key=key,
            preview_id=None,
            admin=request.xray_admin,
            cloud_credential_version=node.cloud_credential_version,
        )
    return _operation_response(operation)


@admin_endpoint("GET")
def node_detail(request, node_id):
    node = ManagedNode.objects.select_related("pool", "cloud_account").get(pk=node_id)
    return JsonResponse(node_representation(node))


@admin_endpoint("POST", recent=True)
def node_action(request, node_id, action):
    allowed = {"start", "stop", "reboot", "reinstall", "quarantine"}
    if action not in allowed:
        raise DomainError("OPERATION_KIND_UNSUPPORTED", "不支持的节点操作", status_code=400)
    node = ManagedNode.objects.select_related("cloud_credential_version").get(pk=node_id)
    payload = json_payload(request)
    key = _uuid(request.headers.get("Idempotency-Key"), "Idempotency-Key")
    preview_id = payload.get("preview_id")
    if action in {"reinstall", "quarantine"} and not preview_id:
        raise DomainError("PREVIEW_REQUIRED", "危险操作需要有效预览", status_code=409)
    params = {
        "region": node.region,
        "account_id": str(node.cloud_account_id),
        "confirmation": str(payload.get("confirmation") or ""),
    }
    operation = OperationService.submit(
        kind=f"node.{action}",
        target_id=node.pk,
        params=params,
        key=key,
        preview_id=_uuid(preview_id, "preview_id") if preview_id else None,
        admin=request.xray_admin,
        cloud_credential_version=node.cloud_credential_version,
    )
    return _operation_response(operation)
