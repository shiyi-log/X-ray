from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from django.db import transaction

from common.errors import DomainError
from common.regions import normalize_region

from .models import ManagedNode, NodePool


def reserve_node(
    pool_id: UUID,
    *,
    account_id: UUID,
    region: str,
    plan_id: str,
    image_id: str,
    operation_key: UUID,
) -> ManagedNode:
    from apps.cloud_accounts.models import CloudAccount

    region = normalize_region(region)
    with transaction.atomic():
        pool = NodePool.objects.select_for_update().get(pk=pool_id)
        if not pool.allow_create:
            raise DomainError("POOL_CREATION_DISABLED", "节点池已禁止创建", status_code=409)
        existing = ManagedNode.objects.filter(pool=pool, operation_key=operation_key).first()
        if existing:
            return existing
        used = ManagedNode.objects.filter(pool=pool, consumes_quota=True).count()
        if used >= pool.quota:
            raise DomainError("POOL_QUOTA_EXCEEDED", "节点额度已用完", status_code=409)
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
        used = ManagedNode.objects.filter(pool=pool, consumes_quota=True).count()
        if quota < used:
            raise DomainError("QUOTA_BELOW_USAGE", "额度不能低于当前占用", status_code=409)
        pool.quota = quota
        pool.save(update_fields=["quota", "updated_at"])
        return pool
