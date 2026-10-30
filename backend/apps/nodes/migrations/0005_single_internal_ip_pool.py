from collections import Counter, defaultdict

from django.db import migrations


def consolidate_pools(apps, schema_editor):
    NodePool = apps.get_model("nodes", "NodePool")
    Allocation = apps.get_model("nodes", "NodePoolRegionAllocation")
    ManagedNode = apps.get_model("nodes", "ManagedNode")

    pools = list(NodePool.objects.order_by("created_at", "pk"))
    if not pools:
        return

    canonical = pools[0]
    pool_ids = [pool.pk for pool in pools]
    quotas = defaultdict(int)
    used_by_pool_region = Counter(
        ManagedNode.objects.filter(pool_id__in=pool_ids, consumes_quota=True).values_list(
            "pool_id", "region"
        )
    )
    used_by_region = Counter()
    for (_pool_id, region), count in used_by_pool_region.items():
        used_by_region[region] += count

    for pool in pools:
        if pool.allow_create:
            allocations = list(Allocation.objects.filter(pool_id=pool.pk))
            if allocations:
                for allocation in allocations:
                    quotas[allocation.region] += allocation.quota
            else:
                quotas[pool.region] += max(int(pool.quota or 1), 1)
        else:
            for (pool_id, region), count in used_by_pool_region.items():
                if pool_id == pool.pk:
                    quotas[region] += count

    for region, count in used_by_region.items():
        quotas[region] = max(quotas[region], count)
    if not quotas:
        quotas[canonical.region or "ap-southeast-1"] = 1

    ManagedNode.objects.filter(pool_id__in=pool_ids).exclude(pool_id=canonical.pk).update(
        pool_id=canonical.pk
    )
    Allocation.objects.filter(pool_id__in=pool_ids).delete()
    NodePool.objects.exclude(pk=canonical.pk).delete()

    ordered_regions = sorted(quotas)
    canonical.name = "IP"
    canonical.region = ordered_regions[0]
    canonical.quota = sum(quotas.values())
    canonical.allow_create = any(pool.allow_create for pool in pools)
    canonical.save(update_fields=["name", "region", "quota", "allow_create"])
    for region, quota in sorted(quotas.items()):
        Allocation.objects.create(pool_id=canonical.pk, region=region, quota=quota)


class Migration(migrations.Migration):
    dependencies = [("nodes", "0004_nodepoolregionallocation")]

    operations = [migrations.RunPython(consolidate_pools, migrations.RunPython.noop)]
