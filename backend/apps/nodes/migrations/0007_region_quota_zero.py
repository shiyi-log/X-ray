from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("nodes", "0006_enforce_single_pool_and_remove_pause")]

    operations = [
        migrations.RemoveConstraint(
            model_name="nodepool",
            name="node_pool_quota_positive",
        ),
        migrations.AddConstraint(
            model_name="nodepool",
            constraint=models.CheckConstraint(
                condition=models.Q(quota__gte=0), name="node_pool_quota_positive"
            ),
        ),
        migrations.RemoveConstraint(
            model_name="nodepoolregionallocation",
            name="node_pool_region_quota_positive",
        ),
        migrations.AddConstraint(
            model_name="nodepoolregionallocation",
            constraint=models.CheckConstraint(
                condition=models.Q(quota__gte=0),
                name="node_pool_region_quota_positive",
            ),
        ),
    ]
