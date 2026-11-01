from django.db import migrations, models
import django.db.models.deletion
import uuid


def create_default_pool_and_assign(apps, schema_editor):
    SubscriptionPool = apps.get_model("subscriptions", "SubscriptionPool")
    Subscription = apps.get_model("subscriptions", "Subscription")
    pool = SubscriptionPool.objects.create(name="default", singleton_key=1)
    Subscription.objects.filter(pool__isnull=True).update(pool=pool)


class Migration(migrations.Migration):
    dependencies = [("subscriptions", "0005_subscriptionmutation_subscriptionplan_and_more")]

    operations = [
        migrations.CreateModel(
            name="SubscriptionPool",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "singleton_key",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, unique=True
                    ),
                ),
                ("name", models.CharField(default="default", max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("singleton_key", 1)),
                        name="subscription_pool_singleton_key_one",
                    )
                ]
            },
        ),
        migrations.AddField(
            model_name="subscription",
            name="pool",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="subscriptions",
                to="subscriptions.subscriptionpool",
            ),
        ),
        migrations.RunPython(create_default_pool_and_assign, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="subscription",
            name="pool",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="subscriptions",
                to="subscriptions.subscriptionpool",
            ),
        ),
    ]
