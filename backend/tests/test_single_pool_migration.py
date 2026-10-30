import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_pool_migration_merges_region_quotas_and_reassigns_nodes(cloud_account):
    executor = MigrationExecutor(connection)
    latest_targets = executor.loader.graph.leaf_nodes()
    executor.migrate([("nodes", "0004_nodepoolregionallocation")])
    old_apps = executor.loader.project_state(
        [("nodes", "0004_nodepoolregionallocation")]
    ).apps
    NodePool = old_apps.get_model("nodes", "NodePool")
    Allocation = old_apps.get_model("nodes", "NodePoolRegionAllocation")
    ManagedNode = old_apps.get_model("nodes", "ManagedNode")

    try:
        first = NodePool.objects.create(name="old-east", region="us-east-1", quota=2)
        second = NodePool.objects.create(
            name="old-apac", region="ap-east-1", quota=1, allow_create=False
        )
        Allocation.objects.create(pool_id=first.pk, region="us-east-1", quota=2)
        Allocation.objects.create(pool_id=second.pk, region="us-east-1", quota=3)
        Allocation.objects.create(pool_id=second.pk, region="ap-east-1", quota=1)
        ManagedNode.objects.create(
            pool_id=first.pk,
            cloud_account_id=cloud_account.pk,
            cloud_credential_version_id=cloud_account.credential_versions.get().pk,
            region="us-east-1",
            plan_id="nano",
            image_id="debian-12",
            deterministic_name="xray-old-east",
            operation_key="11111111-1111-4111-8111-111111111111",
        )
        ManagedNode.objects.create(
            pool_id=second.pk,
            cloud_account_id=cloud_account.pk,
            cloud_credential_version_id=cloud_account.credential_versions.get().pk,
            region="ap-east-1",
            plan_id="nano",
            image_id="debian-12",
            deterministic_name="xray-old-apac",
            operation_key="22222222-2222-4222-8222-222222222222",
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("nodes", "0006_enforce_single_pool_and_remove_pause")])
        new_apps = executor.loader.project_state(
            [("nodes", "0006_enforce_single_pool_and_remove_pause")]
        ).apps
        NewPool = new_apps.get_model("nodes", "NodePool")
        NewAllocation = new_apps.get_model("nodes", "NodePoolRegionAllocation")
        NewNode = new_apps.get_model("nodes", "ManagedNode")

        pools = list(NewPool.objects.all())
        assert len(pools) == 1
        pool = pools[0]
        assert pool.name == "IP"
        assert pool.quota == 3
        assert pool.allow_create is True
        assert NewPool._meta.get_field("allow_create")
        assert dict(
            NewAllocation.objects.filter(pool_id=pool.pk).values_list("region", "quota")
        ) == {"ap-east-1": 1, "us-east-1": 2}
        assert set(NewNode.objects.values_list("pool_id", flat=True)) == {pool.pk}
    finally:
        MigrationExecutor(connection).migrate(latest_targets)


@pytest.mark.django_db(transaction=True)
def test_pool_migration_preserves_pause_and_only_used_quota(cloud_account):
    executor = MigrationExecutor(connection)
    latest_targets = executor.loader.graph.leaf_nodes()
    executor.migrate([("nodes", "0004_nodepoolregionallocation")])
    old_apps = executor.loader.project_state(
        [("nodes", "0004_nodepoolregionallocation")]
    ).apps
    NodePool = old_apps.get_model("nodes", "NodePool")
    Allocation = old_apps.get_model("nodes", "NodePoolRegionAllocation")
    ManagedNode = old_apps.get_model("nodes", "ManagedNode")

    try:
        pool = NodePool.objects.create(
            name="paused-pool", region="us-east-1", quota=5, allow_create=False
        )
        Allocation.objects.create(pool_id=pool.pk, region="us-east-1", quota=4)
        Allocation.objects.create(pool_id=pool.pk, region="ap-east-1", quota=3)
        ManagedNode.objects.create(
            pool_id=pool.pk,
            cloud_account_id=cloud_account.pk,
            cloud_credential_version_id=cloud_account.credential_versions.get().pk,
            region="us-east-1",
            plan_id="nano",
            image_id="debian-12",
            deterministic_name="xray-paused-east",
            operation_key="33333333-3333-4333-8333-333333333333",
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("nodes", "0006_enforce_single_pool_and_remove_pause")])
        new_apps = executor.loader.project_state(
            [("nodes", "0006_enforce_single_pool_and_remove_pause")]
        ).apps
        NewPool = new_apps.get_model("nodes", "NodePool")
        NewAllocation = new_apps.get_model("nodes", "NodePoolRegionAllocation")

        migrated = NewPool.objects.get()
        assert migrated.name == "IP"
        assert migrated.allow_create is False
        assert migrated.quota == 1
        assert dict(
            NewAllocation.objects.filter(pool_id=migrated.pk).values_list("region", "quota")
        ) == {"us-east-1": 1}

        from apps.nodes.models import NodePool as CurrentNodePool
        from apps.nodes.quota import set_allocations

        reopened = set_allocations(
            CurrentNodePool.objects.get(pk=migrated.pk).pk,
            [{"region": "us-east-1", "quota": 2}],
        )
        assert reopened.allow_create is True
    finally:
        MigrationExecutor(connection).migrate(latest_targets)
