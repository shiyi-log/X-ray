from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("identity", "0006_nodeautomationsetting")]

    operations = [
        migrations.AddField(
            model_name="nodeautomationsetting",
            name="daily_restart_last_success_node_id",
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
