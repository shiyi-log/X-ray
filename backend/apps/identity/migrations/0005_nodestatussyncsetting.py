from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("identity", "0004_provideridentitynetworksetting")]

    operations = [
        migrations.CreateModel(
            name="NodeStatusSyncSetting",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "singleton_key",
                    models.PositiveSmallIntegerField(default=1, editable=False, unique=True),
                ),
                ("enabled", models.BooleanField(default=False)),
                ("interval_minutes", models.PositiveSmallIntegerField(default=60)),
                ("last_scheduled_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddConstraint(
            model_name="nodestatussyncsetting",
            constraint=models.CheckConstraint(
                condition=models.Q(singleton_key=1), name="node_status_sync_singleton_key_one"
            ),
        ),
        migrations.AddConstraint(
            model_name="nodestatussyncsetting",
            constraint=models.CheckConstraint(
                condition=models.Q(interval_minutes__gte=5, interval_minutes__lte=1440),
                name="node_status_sync_interval_range",
            ),
        ),
    ]
