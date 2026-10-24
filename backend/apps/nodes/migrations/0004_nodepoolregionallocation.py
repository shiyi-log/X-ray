from django.db import migrations, models
import django.db.models.deletion
import uuid


def copy_legacy_pool_quotas(apps, schema_editor):
    NodePool = apps.get_model("nodes", "NodePool")
    Allocation = apps.get_model("nodes", "NodePoolRegionAllocation")
    for pool in NodePool.objects.all().iterator():
        Allocation.objects.get_or_create(
            pool_id=pool.pk,
            region=pool.region or "ap-southeast-1",
            defaults={"quota": max(int(pool.quota or 1), 1)},
        )


def remove_copied_allocations(apps, schema_editor):
    Allocation = apps.get_model("nodes", "NodePoolRegionAllocation")
    Allocation.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("nodes", "0003_nodepool_region")]

    operations = [
        migrations.CreateModel(
            name="NodePoolRegionAllocation",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("region", models.CharField(max_length=120)),
                ("quota", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "pool",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="region_allocations",
                        to="nodes.nodepool",
                    ),
                ),
            ],
            options={"ordering": ["region", "pk"]},
        ),
        migrations.AddConstraint(
            model_name="nodepoolregionallocation",
            constraint=models.UniqueConstraint(
                fields=("pool", "region"), name="unique_node_pool_region_allocation"
            ),
        ),
        migrations.AddConstraint(
            model_name="nodepoolregionallocation",
            constraint=models.CheckConstraint(
                condition=models.Q(("quota__gte", 1)), name="node_pool_region_quota_positive"
            ),
        ),
        migrations.RunPython(copy_legacy_pool_quotas, remove_copied_allocations),
    ]
