from __future__ import annotations

from uuid import UUID

from django.db import transaction
from django.http import JsonResponse

from apps.operations.models import Operation
from apps.operations.services import ActionPreviewService, OperationService
from common.admin_api import admin_endpoint, json_payload, paginated_response
from common.errors import DomainError
from common.regions import normalize_region

from .models import ManagedNode, NodePool
from .quota import reserve_node, set_allocations, set_allow_create, set_quota
from .serializers import node_pool_representation, node_representation, with_node_traffic


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


def _node_delete_snapshot(node: ManagedNode) -> dict:
    return {
        "external_id": node.external_id,
        "region": node.region,
        "account_id": str(node.cloud_account_id),
        "addresses": list(node.addresses or []),
        "desired_state": node.desired_state,
        "desired_generation": node.desired_generation,
    }


@admin_endpoint("GET", "POST")
def pool_collection(request):
    if request.method == "GET":
        return paginated_response(
            request, NodePool.objects.filter(singleton_key=1), node_pool_representation
        )
    payload = json_payload(request)
    allow_create = payload.get("allow_create", True)
    if not isinstance(allow_create, bool):
        raise ValueError("allow_create must be a boolean")
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
    if any(int(item.get("quota", 0)) < 0 for item in allocations):
        raise ValueError("allocation quota must be at least 0")
    created = False
    with transaction.atomic():
        pool = NodePool.objects.filter(singleton_key=1).first()
        if pool is None:
            pool = NodePool.objects.create(
                name="IP",
                region=normalize_region(allocations[0].get("region")),
                quota=sum(int(item.get("quota", 0)) for item in allocations),
                allow_create=allow_create,
            )
            created = True
        set_allocations(pool.pk, allocations)
        if "allow_create" in payload and not created:
            set_allow_create(pool.pk, allow_create)
    pool.refresh_from_db()
    return JsonResponse(node_pool_representation(pool), status=201 if created else 200)


@admin_endpoint("GET", "PATCH")
def pool_detail(request, pool_id):
    pool = NodePool.objects.get(pk=pool_id)
    if request.method == "GET":
        return JsonResponse(node_pool_representation(pool))
    payload = json_payload(request)
    unknown = set(payload) - {"region", "quota", "allocations", "allow_create"}
    if unknown:
        raise ValueError(f"unsupported fields: {sorted(unknown)}")
    if "allow_create" in payload and not isinstance(payload["allow_create"], bool):
        raise ValueError("allow_create must be a boolean")
    if "allocations" in payload:
        pool = set_allocations(pool.pk, payload["allocations"])
    elif "quota" in payload:
        pool = set_quota(pool.pk, int(payload["quota"]))
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
        pool = set_allow_create(pool.pk, payload["allow_create"])
    pool.refresh_from_db()
    return JsonResponse(node_pool_representation(pool))


@admin_endpoint("GET", "POST")
def node_collection(request):
    if request.method == "GET":
        nodes = with_node_traffic(ManagedNode.objects.select_related("cloud_account")).order_by(
            "-created_at", "pk"
        )
        if request.GET.get("security_state"):
            nodes = nodes.filter(security_state=request.GET["security_state"])
        return paginated_response(request, nodes, node_representation)

    payload = json_payload(request)
    key = _uuid(request.headers.get("Idempotency-Key"), "Idempotency-Key")
    required = ("account_id", "plan_id", "image_id")
    if any(not payload.get(field) for field in required):
        raise ValueError(f"required fields: {', '.join(required)}")
    if "pool_id" in payload:
        raise ValueError("pool_id is managed internally and must be omitted")
    with transaction.atomic():
        pool = NodePool.objects.filter(singleton_key=1).first()
        if pool is None:
            raise DomainError(
                "REGION_ALLOCATION_REQUIRED", "请先配置地区额度", status_code=409
            )
        requested_region = payload.get("region")
        if requested_region is None or not str(requested_region).strip():
            allocations = list(pool.region_allocations.all())
            if len(allocations) <= 1:
                requested_region = pool.region
            else:
                requested_region = None
        node = reserve_node(
            pool.pk,
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
    node = with_node_traffic(ManagedNode.objects.select_related("cloud_account")).get(
        pk=node_id
    )
    return JsonResponse(node_representation(node))


@admin_endpoint("POST")
def node_refresh(request, node_id):
    json_payload(request)
    key = _uuid(request.headers.get("Idempotency-Key"), "Idempotency-Key")
    with transaction.atomic():
        node = ManagedNode.objects.select_related("cloud_credential_version").get(
            pk=node_id
        )
        if not node.external_id or node.desired_state == "DELETED":
            raise DomainError(
                "NODE_NOT_PROVISIONED", "服务器尚无可刷新的云实例", status_code=409
            )
        operation = OperationService.submit(
            kind="node.refresh",
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


@admin_endpoint("POST", recent=True)
def node_action(request, node_id, action):
    allowed = {"start", "stop", "reboot", "delete", "reinstall", "quarantine"}
    if action not in allowed:
        raise DomainError("OPERATION_KIND_UNSUPPORTED", "不支持的节点操作", status_code=400)
    payload = json_payload(request)
    key = _uuid(request.headers.get("Idempotency-Key"), "Idempotency-Key")
    preview_id = payload.get("preview_id")
    if action in {"delete", "reinstall", "quarantine"} and not preview_id:
        raise DomainError("PREVIEW_REQUIRED", "危险操作需要有效预览", status_code=409)
    with transaction.atomic():
        nodes = ManagedNode.objects.select_related("cloud_credential_version")
        if action == "delete":
            nodes = nodes.select_for_update()
        node = nodes.get(pk=node_id)
        params = {
            "region": node.region,
            "account_id": str(node.cloud_account_id),
            "confirmation": str(payload.get("confirmation") or ""),
        }
        preview_uuid = _uuid(preview_id, "preview_id") if preview_id else None
        if action in {"start", "reboot", "delete"}:
            if not node.external_id or node.desired_state == "DELETED":
                raise DomainError(
                    "NODE_NOT_PROVISIONED", "服务器尚无可操作的云实例", status_code=409
                )
        if action == "delete":
            already_submitted = Operation.objects.filter(
                admin=request.xray_admin,
                kind="node.delete",
                target_id=node.pk,
                idempotency_key=key,
            ).exists()
            if not already_submitted:
                preview = ActionPreviewService.validate(
                    preview_uuid,
                    admin=request.xray_admin,
                    kind="node.delete",
                    target_id=node.pk,
                    params=params,
                    confirmation=params["confirmation"],
                )
                if preview.snapshot != _node_delete_snapshot(node):
                    raise DomainError(
                        "PREVIEW_STALE", "服务器状态已变化，请重新生成删除预览", status_code=409
                    )
        operation = OperationService.submit(
            kind=f"node.{action}",
            target_id=node.pk,
            params=params,
            key=key,
            preview_id=preview_uuid,
            admin=request.xray_admin,
            cloud_credential_version=node.cloud_credential_version,
        )
    return _operation_response(operation)
