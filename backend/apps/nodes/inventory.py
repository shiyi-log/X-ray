from __future__ import annotations

from collections import Counter, defaultdict

from apps.nodes.models import ManagedNode, NodeResource
from common.errors import DomainError
from providers.registry import build_read_provider


def reconcile_cloud_account_inventory(account):
    """Compare managed instance IDs with a complete read-only regional cloud listing."""
    if not account.enabled:
        raise DomainError("CLOUD_ACCOUNT_DISABLED", "云账号已停用", status_code=409)

    managed_nodes = list(
        ManagedNode.objects.filter(cloud_account=account)
        .exclude(desired_state="DELETED")
        .only("id", "region", "external_id")
        .order_by("region", "pk")
    )
    active_resources = list(
        NodeResource.objects.filter(
            node__cloud_account=account,
            node__desired_state__in=("PRESENT", "STOPPED"),
            kind="instance",
            cost_status="ACTIVE",
        )
        .select_related("node")
        .only("external_id", "node_id", "node__external_id")
    )
    resources_by_node = defaultdict(list)
    for resource in active_resources:
        resources_by_node[resource.node_id].append(resource.external_id)

    managed_by_region = defaultdict(set)
    pending_managed_nodes = 0
    managed_instance_ids = []
    resource_binding_error_count = 0
    resource_owner_counts = Counter()
    for node in managed_nodes:
        node_resources = resources_by_node.get(node.pk, [])
        if not node.external_id:
            pending_managed_nodes += 1
            if node_resources:
                resource_binding_error_count += len(node_resources)
            continue

        managed_instance_ids.append(node.external_id)
        managed_by_region[node.region].add(node.external_id)
        resource_owner_counts[(node.region, node.external_id)] += 1
        if node_resources != [node.external_id]:
            resource_binding_error_count += 1

    resource_binding_error_count += sum(
        count - 1 for count in resource_owner_counts.values() if count > 1
    )
    primary_region = next(
        (node.region for node in managed_nodes if node.region), "ap-southeast-1"
    )
    identity_reader = build_read_provider(account.pk, primary_region)
    identity = identity_reader.validate_credentials()
    if (
        identity.provider != account.provider
        or identity.external_account_id != account.external_account_id
    ):
        raise DomainError("CLOUD_IDENTITY_MISMATCH", "云身份与已绑定账号不一致", status_code=409)

    try:
        available_regions = tuple(identity_reader.list_regions())
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError(
            "CLOUD_INVENTORY_READ_FAILED", "读取云区域清单失败", status_code=502
        ) from exc
    if not available_regions:
        raise DomainError(
            "CLOUD_INVENTORY_REGIONS_UNAVAILABLE",
            "云账号未返回可核对区域清单",
            status_code=502,
        )
    region_ids = {region.id for region in available_regions if region.id}
    region_ids.update(node.region for node in managed_nodes if node.region)
    regions = sorted(region_ids)
    instances_by_region = {}
    failed_regions = []
    for region in regions:
        try:
            reader = (
                identity_reader
                if region == primary_region
                else build_read_provider(account.pk, region)
            )
            if reader is not identity_reader:
                region_identity = reader.validate_credentials()
                if (
                    region_identity.provider != account.provider
                    or region_identity.external_account_id != account.external_account_id
                ):
                    raise DomainError(
                        "CLOUD_IDENTITY_MISMATCH",
                        "云身份与已绑定账号不一致",
                        status_code=409,
                    )
            instances = reader.list_instances(region)
            if any(
                instance.ref.account.id != account.pk
                or instance.ref.account.provider != account.provider
                or instance.ref.account.external_account_id != account.external_account_id
                or instance.ref.region != region
                for instance in instances
            ):
                raise DomainError(
                    "RESOURCE_OWNERSHIP_MISMATCH",
                    "实例清单包含其他账号或区域的资源",
                    status_code=409,
                )
            resource_ids = [instance.ref.resource_id for instance in instances]
            duplicate_ids = len(set(resource_ids)) != len(resource_ids)
            if any(not resource_id for resource_id in resource_ids) or duplicate_ids:
                raise DomainError(
                    "CLOUD_INVENTORY_RESPONSE_INVALID",
                    "实例清单包含无效或重复实例标识",
                    status_code=502,
                )
            instances_by_region[region] = set(resource_ids)
        except DomainError as exc:
            failed_regions.append({"region": region, "error_code": exc.code})
        except Exception:
            failed_regions.append({"region": region, "error_code": "CLOUD_INVENTORY_READ_FAILED"})

    complete_regions = sorted(instances_by_region)
    untracked_cloud = []
    missing_managed = []
    for region in complete_regions:
        for external_id in sorted(instances_by_region[region] - managed_by_region[region]):
            untracked_cloud.append({"region": region, "external_id": external_id})
        for external_id in sorted(managed_by_region[region] - instances_by_region[region]):
            missing_managed.append({"region": region, "external_id": external_id})

    return {
        "account_id": str(account.pk),
        "provider": account.provider,
        "checked_regions": regions,
        "complete_regions": complete_regions,
        "failed_regions": failed_regions,
        "complete": not failed_regions and complete_regions == regions,
        "managed_node_count": len(managed_nodes),
        "tracked_cloud_instance_count": len(managed_instance_ids),
        "pending_managed_node_count": pending_managed_nodes,
        "active_instance_resource_count": len(active_resources),
        "resource_binding_error_count": resource_binding_error_count,
        "cloud_instance_count": sum(len(values) for values in instances_by_region.values()),
        "untracked_cloud_instances": untracked_cloud,
        "missing_managed_instances": missing_managed,
        "node_count_reconciled": (
            not failed_regions
            and not pending_managed_nodes
            and not resource_binding_error_count
            and not untracked_cloud
            and not missing_managed
            and len(managed_instance_ids)
            == sum(len(values) for values in instances_by_region.values())
        ),
        "automatic_actions": [],
    }
