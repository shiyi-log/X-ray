from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("identity", "0005_nodestatussyncsetting")]

    operations = [
        migrations.CreateModel(
            name="NodeAutomationSetting",
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
                ("pool_sync_enabled", models.BooleanField(default=False)),
                ("pool_sync_interval_minutes", models.PositiveSmallIntegerField(default=15)),
                ("pool_sync_creation_templates", models.JSONField(blank=True, default=list)),
                ("pool_sync_last_scheduled_at", models.DateTimeField(blank=True, null=True)),
                ("daily_restart_enabled", models.BooleanField(default=False)),
                ("daily_restart_time", models.CharField(default="04:00", max_length=5)),
                (
                    "daily_restart_timezone",
                    models.CharField(default="Asia/Shanghai", max_length=64),
                ),
                ("daily_restart_last_local_date", models.DateField(blank=True, null=True)),
                ("daily_restart_last_node_id", models.UUIDField(blank=True, null=True)),
                ("daily_restart_last_scheduled_at", models.DateTimeField(blank=True, null=True)),
                ("usage_sync_enabled", models.BooleanField(default=True)),
                ("usage_sync_interval_minutes", models.PositiveSmallIntegerField(default=1)),
                ("usage_sync_last_scheduled_at", models.DateTimeField(blank=True, null=True)),
                ("policy_version", models.PositiveBigIntegerField(default=1)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddConstraint(
            model_name="nodeautomationsetting",
            constraint=models.CheckConstraint(
                condition=models.Q(singleton_key=1), name="node_automation_singleton_key_one"
            ),
        ),
        migrations.AddConstraint(
            model_name="nodeautomationsetting",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    pool_sync_interval_minutes__gte=5,
                    pool_sync_interval_minutes__lte=1440,
                ),
                name="node_automation_pool_interval_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="nodeautomationsetting",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    usage_sync_interval_minutes__gte=1,
                    usage_sync_interval_minutes__lte=1440,
                ),
                name="node_automation_usage_interval_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="nodeautomationsetting",
            constraint=models.CheckConstraint(
                condition=models.Q(policy_version__gte=1),
                name="node_automation_policy_version_positive",
            ),
        ),
    ]
