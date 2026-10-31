from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from django.db import transaction
from django.db.models import Count

from common.errors import DomainError
from common.regions import is_supported_region, normalize_region

from .models import ManagedNode, NodePool, NodePoolRegionAllocation


def ensure_pool_allocations(pool: NodePool) -> list[NodePoolRegionAllocation]:
    """Return allocations, creating a legacy single-region allocation if needed."""

    allocations = list(pool.region_allocations.all())
    if allocations:
        return allocations
    allocation = NodePoolRegionAllocation.objects.create(
        pool=pool,
        region=normalize_region(pool.region),
        quota=max(int(pool.quota or 1), 1),
    )
    return [allocation]


def reserve_node(
    pool_id: UUID,
    *,
    account_id: UUID,
    region: str | None = None,
    plan_id: str,
    image_id: str,
    operation_key: UUID,
) -> ManagedNode:
    from apps.cloud_accounts.models import CloudAccount

    with transaction.atomic():
        pool = NodePool.objects.select_for_update().get(pk=pool_id)
        existing = ManagedNode.objects.filter(pool=pool, operation_key=operation_key).first()
        if existing:
            return existing
        if not pool.allow_create:
            raise DomainError("POOL_CREATION_DISABLED", "节点池已禁止创建", status_code=409)
        allocations = ensure_pool_allocations(pool)
        if region is None or not str(region).strip():
            if len(allocations) != 1:
                raise DomainError(
                    "POOL_REGION_REQUIRED",
                    "多地区节点池创建节点时必须指定地区",
                    status_code=400,
                )
            requested_region = allocations[0].region
        else:
            requested_region = normalize_region(region)
        allocation = next(
            (item for item in allocations if item.region == requested_region), None
        )
        if allocation is None:
            if len(allocations) == 1:
                raise DomainError(
                    "POOL_REGION_MISMATCH",
                    "节点地区必须与节点池已分配地区一致",
                    status_code=409,
                )
            raise DomainError(
                "POOL_REGION_UNALLOCATED",
                "该地区未在节点池中分配额度",
                status_code=409,
            )
        allocation = NodePoolRegionAllocation.objects.select_for_update().get(pk=allocation.pk)
        region = allocation.region
        used = ManagedNode.objects.filter(
            pool=pool, region=region, consumes_quota=True
        ).count()
        if used >= allocation.quota:
            raise DomainError(
                "POOL_QUOTA_EXCEEDED", "该地区节点额度已用完", status_code=409
            )
        account = CloudAccount.objects.select_for_update().get(pk=account_id)
        if not account.enabled:
            raise DomainError("CLOUD_ACCOUNT_DISABLED", "云账号已停用", status_code=409)
        credential = account.credential_versions.get(version=account.credential_version)
        node_id = uuid5(NAMESPACE_URL, f"xray-node:{pool.pk}:{operation_key}")
        name = f"xray-{str(pool.pk)[:8]}-{str(node_id)[:8]}"
        return ManagedNode.objects.create(
            id=node_id,
            pool=pool,
            cloud_account=account,
            cloud_credential_version=credential,
            region=region,
            plan_id=plan_id,
            image_id=image_id,
            deterministic_name=name,
            operation_key=operation_key,
            consumes_quota=True,
        )


def release_quota(node_id: UUID, *, cloud_absence_confirmed: bool) -> ManagedNode:
    if not cloud_absence_confirmed:
        raise DomainError(
            "RESOURCE_ABSENCE_UNCONFIRMED",
            "未确认云资源已不存在，不能释放额度",
            status_code=409,
        )
    with transaction.atomic():
        node = ManagedNode.objects.select_for_update().get(pk=node_id)
        node.consumes_quota = False
        node.desired_state = "DELETED"
        node.provisioning_state = "DELETED"
        node.save(
            update_fields=[
                "consumes_quota",
                "desired_state",
                "provisioning_state",
                "updated_at",
            ]
        )
        return node


def set_quota(pool_id: UUID, quota: int) -> NodePool:
    if quota < 1:
        raise DomainError("INVALID_QUOTA", "额度必须至少为 1", status_code=400)
    with transaction.atomic():
        pool = NodePool.objects.select_for_update().get(pk=pool_id)
        allocations = ensure_pool_allocations(pool)
        used = ManagedNode.objects.filter(pool=pool, consumes_quota=True).count()
        if quota < used:
            raise DomainError(
                "QUOTA_BELOW_USAGE", "额度不能低于当前占用", status_code=409
            )
        # Legacy quota updates resize the single allocation. For multi-region
        # pools, callers should use set_allocations so each region is explicit.
        if len(allocations) != 1:
            raise DomainError(
                "MULTI_REGION_ALLOCATION_REQUIRED",
                "多地区节点池必须分别调整各地区额度",
                status_code=400,
            )
        allocation = allocations[0]
        region_used = ManagedNode.objects.filter(
            pool=pool, region=allocation.region, consumes_quota=True
        ).count()
        if quota < region_used:
            raise DomainError(
                "QUOTA_BELOW_USAGE", "额度不能低于当前占用", status_code=409
            )
        allocation.quota = quota
        allocation.save(update_fields=["quota", "updated_at"])
        pool.quota = quota
        pool.region = allocation.region
        pool.save(update_fields=["quota", "region", "updated_at"])
        return pool


def set_allocations(pool_id: UUID, raw_allocations: object) -> NodePool:
    """Replace a pool's region allocations after enforcing current usage."""

    if not isinstance(raw_allocations, list) or not raw_allocations:
        raise ValueError("allocations must be a non-empty list")
    parsed: list[tuple[str, int]] = []
    seen: set[str] = set()
    for item in raw_allocations:
        if not isinstance(item, dict):
            raise ValueError("each allocation must be an object")
        region = normalize_region(item.get("region"))
        quota = int(item.get("quota", 0))
        if quota < 1:
            raise ValueError("allocation quota must be at least 1")
        if region in seen:
            raise ValueError("allocation regions must be unique")
        seen.add(region)
        parsed.append((region, quota))

    with transaction.atomic():
        pool = NodePool.objects.select_for_update().get(pk=pool_id)
        current = dict(
            ManagedNode.objects.filter(pool=pool, consumes_quota=True)
            .values("region")
            .annotate(usage=Count("pk"))
            .values_list("region", "usage")
        )
        existing = {
            item.region: item
            for item in pool.region_allocations.select_for_update()
        }
        for region, _quota in parsed:
            if (
                not is_supported_region(region)
                and region not in existing
                and region not in current
            ):
                raise ValueError(f"unsupported region: {region}")
        for region, quota in parsed:
            if quota < current.get(region, 0):
                raise DomainError(
                    "QUOTA_BELOW_USAGE",
                    f"{region} 额度不能低于当前占用",
                    status_code=409,
                )
        removed = set(current) - {region for region, _quota in parsed}
        if removed:
            raise DomainError(
                "REGION_ALLOCATION_IN_USE",
                "已有节点的地区不能移除分配",
                status_code=409,
            )
        for region, quota in parsed:
            allocation = existing.get(region)
            if allocation:
                allocation.quota = quota
                allocation.save(update_fields=["quota", "updated_at"])
            else:
                NodePoolRegionAllocation.objects.create(pool=pool, region=region, quota=quota)
        stale_regions = set(existing) - {region for region, _quota in parsed}
        if stale_regions:
            pool.region_allocations.filter(region__in=stale_regions).delete()
        pool.quota = sum(quota for _region, quota in parsed)
        pool.region = parsed[0][0]
        pool.save(update_fields=["quota", "region", "updated_at"])
        return pool


def set_allow_create(pool_id: UUID, allow_create: bool) -> NodePool:
    if not isinstance(allow_create, bool):
        raise ValueError("allow_create must be a boolean")
    with transaction.atomic():
        pool = NodePool.objects.select_for_update().get(pk=pool_id)
        if pool.allow_create != allow_create:
            pool.allow_create = allow_create
            pool.save(update_fields=["allow_create", "updated_at"])
        return pool
