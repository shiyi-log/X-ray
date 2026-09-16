from __future__ import annotations

from .models import ManagedNode, NodePool


def node_pool_representation(pool: NodePool) -> dict:
    used = pool.nodes.filter(consumes_quota=True).count()
    return {
        "id": str(pool.pk),
        "name": pool.name,
        "quota": pool.quota,
        "used": used,
        "available": max(pool.quota - used, 0),
        "allow_create": pool.allow_create,
        "created_at": pool.created_at.isoformat(),
        "updated_at": pool.updated_at.isoformat(),
    }


def node_representation(node: ManagedNode) -> dict:
    return {
        "id": str(node.pk),
        "name": node.deterministic_name,
        "pool_id": str(node.pool_id),
        "pool_name": node.pool.name,
        "cloud_account_id": str(node.cloud_account_id),
        "cloud_account_name": node.cloud_account.name,
        "provider": node.cloud_account.provider,
        "region": node.region,
        "plan_id": node.plan_id,
        "image_id": node.image_id,
        "external_id": node.external_id,
        "addresses": node.addresses,
        "raw_cloud_state": node.raw_cloud_state,
        "desired_state": node.desired_state,
        "provisioning_state": node.provisioning_state,
        "health_state": node.health_state,
        "security_state": node.security_state,
        "consumes_quota": node.consumes_quota,
        "desired_generation": node.desired_generation,
        "applied_generation": node.applied_generation,
        "observed_at": node.observed_at.isoformat() if node.observed_at else None,
        "observation_error": node.observation_error,
        "last_error_code": node.last_error_code,
        "created_at": node.created_at.isoformat(),
        "updated_at": node.updated_at.isoformat(),
    }
