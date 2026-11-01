import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_subscription_pool_migration_assigns_existing_subscriptions_to_one_pool():
    old_target = ("subscriptions", "0005_subscriptionmutation_subscriptionplan_and_more")
    new_target = ("subscriptions", "0006_subscriptionpool_and_subscription_pool")
    latest_targets = MigrationExecutor(connection).loader.graph.leaf_nodes()
    MigrationExecutor(connection).migrate([old_target])
    old_apps = MigrationExecutor(connection).loader.project_state([old_target]).apps
    AccessProfile = old_apps.get_model("subscriptions", "AccessProfile")
    Subscription = old_apps.get_model("subscriptions", "Subscription")

    try:
        first_profile = AccessProfile.objects.create(name="existing-subscription-one")
        second_profile = AccessProfile.objects.create(name="existing-subscription-two")
        Subscription.objects.create(
            profile_id=first_profile.pk,
            token_digest="a" * 64,
            token_epoch=1,
            status="ACTIVE",
        )
        Subscription.objects.create(
            profile_id=second_profile.pk,
            token_digest="b" * 64,
            token_epoch=1,
            status="ACTIVE",
        )

        MigrationExecutor(connection).migrate([new_target])
        new_apps = MigrationExecutor(connection).loader.project_state([new_target]).apps
        SubscriptionPool = new_apps.get_model("subscriptions", "SubscriptionPool")
        MigratedSubscription = new_apps.get_model("subscriptions", "Subscription")

        assert SubscriptionPool.objects.count() == 1
        pool = SubscriptionPool.objects.get()
        assert pool.singleton_key == 1
        assert set(MigratedSubscription.objects.values_list("pool_id", flat=True)) == {pool.pk}
    finally:
        MigrationExecutor(connection).migrate(latest_targets)
