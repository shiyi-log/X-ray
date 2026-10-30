from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("nodes", "0005_single_internal_ip_pool")]

    operations = [
        migrations.AddField(
            model_name="nodepool",
            name="singleton_key",
            field=models.PositiveSmallIntegerField(default=1, editable=False, unique=True),
        ),
        migrations.AddConstraint(
            model_name="nodepool",
            constraint=models.CheckConstraint(
                condition=models.Q(singleton_key=1), name="node_pool_singleton_key_one"
            ),
        ),
    ]
