from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("nodes", "0008_managednode_usage_sync_retry")]

    operations = [
        migrations.AddField(
            model_name="managednode",
            name="usage_sync_lease_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="managednode",
            name="usage_sync_lease_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="managednode",
            index=models.Index(
                fields=["usage_sync_lease_expires_at"], name="node_usage_lease_exp_idx"
            ),
        ),
    ]
