from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("nodes", "0007_region_quota_zero")]

    operations = [
        migrations.AddField(
            model_name="managednode",
            name="usage_sync_retry_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="managednode",
            name="usage_sync_retry_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="managednode",
            index=models.Index(
                fields=["usage_sync_retry_at"], name="node_usage_retry_at_idx"
            ),
        ),
    ]
