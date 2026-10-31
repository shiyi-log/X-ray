from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("identity", "0003_adminsession_absolute_expires_at_and_more")]

    operations = [
        migrations.CreateModel(
            name="ProviderIdentityNetworkSetting",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "singleton_key",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, unique=True
                    ),
                ),
                ("enabled", models.BooleanField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("singleton_key", 1)),
                        name="provider_identity_network_singleton_key_one",
                    )
                ],
            },
        ),
    ]
