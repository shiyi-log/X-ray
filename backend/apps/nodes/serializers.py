from __future__ import annotations

import ast

from django.db.models import Count, Max, Sum

from .models import ManagedNode, NodePool, NodePoolRegionAllocation


def _allocation_representation(allocation: NodePoolRegionAllocation, *, used: int) -> dict:
    return {
        "region": allocation.region,
        "quota": allocation.quota,
        "used": used,
        "available": max(allocation.quota - used, 0),
    }


def node_pool_representation(pool: NodePool) -> dict:
    allocations = list(pool.region_allocations.all())
    if not allocations:
        allocations = [
            NodePoolRegionAllocation(
                pool=pool, region=pool.region, quota=max(int(pool.quota or 1), 1)
            )
        ]
    allocation_payload = []
    for allocation in allocations:
        used = pool.nodes.filter(
            region=allocation.region, consumes_quota=True
        ).count()
        allocation_payload.append(_allocation_representation(allocation, used=used))
    used = sum(item["used"] for item in allocation_payload)
    quota = sum(item["quota"] for item in allocation_payload)
    return {
        "id": str(pool.pk),
        "name": pool.name,
        "region": allocations[0].region,
        "regions": [item["region"] for item in allocation_payload],
        "allocations": allocation_payload,
        "quota": quota,
        "used": used,
        "available": max(quota - used, 0),
        "allow_create": pool.allow_create,
        "created_at": pool.created_at.isoformat(),
        "updated_at": pool.updated_at.isoformat(),
    }


def with_node_traffic(nodes):
    return nodes.annotate(
        traffic_sample_count=Count("usagecheckpoint"),
        traffic_upload_bytes=Sum("usagecheckpoint__upload_bytes"),
        traffic_download_bytes=Sum("usagecheckpoint__download_bytes"),
        traffic_sampled_at=Max("usagecheckpoint__sampled_at"),
    )


def _raw_cloud_state(node: ManagedNode) -> str:
    raw_state = node.raw_cloud_state or ""
    if node.cloud_account.provider != "aws_lightsail" or not raw_state.strip().startswith("{"):
        return raw_state
    try:
        parsed_state = ast.literal_eval(raw_state)
    except (SyntaxError, ValueError):
        return raw_state
    if isinstance(parsed_state, dict):
        state_name = parsed_state.get("name")
        if isinstance(state_name, str) and state_name.strip():
            return state_name.strip()
    return raw_state


def node_representation(node: ManagedNode) -> dict:
    from apps.subscriptions.metering import ambiguous_socks_profile_ids

    if hasattr(node, "traffic_sample_count"):
        sample_count = node.traffic_sample_count
        upload_bytes = node.traffic_upload_bytes or 0
        download_bytes = node.traffic_download_bytes or 0
        sampled_at = node.traffic_sampled_at
    else:
        from apps.subscriptions.models import UsageCheckpoint

        traffic = UsageCheckpoint.objects.filter(node_id=node.pk).aggregate(
            samples=Count("pk"),
            upload_bytes=Sum("upload_bytes"),
            download_bytes=Sum("download_bytes"),
            sampled_at=Max("sampled_at"),
        )
        sample_count = traffic["samples"]
        upload_bytes = traffic["upload_bytes"] or 0
        download_bytes = traffic["download_bytes"] or 0
        sampled_at = traffic["sampled_at"]
    return {
        "id": str(node.pk),
        "name": node.deterministic_name,
        "cloud_account_id": str(node.cloud_account_id),
        "cloud_account_name": node.cloud_account.name,
        "provider": node.cloud_account.provider,
        "region": node.region,
        "plan_id": node.plan_id,
        "image_id": node.image_id,
        "external_id": node.external_id,
        "addresses": node.addresses,
        "traffic_upload_bytes": upload_bytes,
        "traffic_download_bytes": download_bytes,
        "traffic_total_bytes": upload_bytes + download_bytes,
        "traffic_sampled_at": sampled_at.isoformat() if sampled_at else None,
        "traffic_state": "COLLECTED" if sample_count else "NO_DATA",
        "metering_coverage": "PARTIAL"
        if ambiguous_socks_profile_ids([node.pk])
        else "SUPPORTED",
        "raw_cloud_state": _raw_cloud_state(node),
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
