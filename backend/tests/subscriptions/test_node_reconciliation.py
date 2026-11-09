from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.nodes.models import ManagedNode, NodeConfigRevision, NodeProtocol
from apps.subscriptions.credentials import CredentialService
from apps.subscriptions.models import (
    AccessProfile,
    NodeCredential,
    Subscription,
    SubscriptionToken,
)
from apps.subscriptions.publishing import NoPublishableEndpoints, Publisher
from apps.subscriptions.tokens import TokenService


def trusted_health(node):
    node.raw_cloud_state = "running"
    node.health_state = "HEALTHY"
    node.provisioning_state = "READY"
    node.save(update_fields=["raw_cloud_state", "health_state", "provisioning_state", "updated_at"])
    NodeConfigRevision.objects.update_or_create(
        node=node,
        generation=node.applied_generation,
        defaults={
            "config_hash": "a" * 64,
            "xray_version": "26.3.27",
            "installer_version": "1.0.0",
            "bundle_hash": "test-bundle",
            "usable": True,
            "probe_result": {
                "generation": node.applied_generation,
                "app_health_passed": True,
                "accepted": True,
                "positive_control": True,
                "fresh_connection": True,
            },
        },
    )


def assigned_profile(node, name):
    protocol = NodeProtocol.objects.create(node=node, protocol="vless", port=18443)
    profile = AccessProfile.objects.create(name=name)
    issued = TokenService.issue(profile.pk)
    credential = CredentialService.rotate(
        node.pk, profile_ids=[profile.pk], protocol_ids=[protocol.pk]
    )[0]
    node.refresh_from_db()
    node.applied_generation = node.desired_generation
    node.save(update_fields=["applied_generation", "updated_at"])
    credential.applied_generation = credential.desired_generation
    credential.save(update_fields=["applied_generation"])
    trusted_health(node)
    return profile, issued, credential


@pytest.mark.django_db
@pytest.mark.parametrize(
    "changes",
    [
        {"raw_cloud_state": "stopped"},
        {"desired_state": "DELETED"},
        {"health_state": "UNHEALTHY"},
        {"observation_error": "CLOUD_READ_FAILED"},
        {"addresses": [{"value": "not-an-ip", "family": 4}]},
        {"addresses": [{"value": "192.0.2.50", "family": 6}]},
    ],
)
def test_publishing_excludes_unusable_node_despite_matching_generations(ready_node, changes):
    profile, issued, _credential = assigned_profile(ready_node, "strict-ready")
    for field, value in changes.items():
        setattr(ready_node, field, value)
    ready_node.save()

    with pytest.raises(NoPublishableEndpoints):
        Publisher.publish(issued.subscription_id)
    assert profile.subscription.current_revision_id is None


@pytest.mark.django_db
def test_publishing_requires_current_generation_health_evidence(ready_node):
    _profile, issued, _credential = assigned_profile(ready_node, "old-probe")
    NodeConfigRevision.objects.filter(node=ready_node).update(
        probe_result={"generation": ready_node.applied_generation - 1, "app_health_passed": True}
    )

    with pytest.raises(NoPublishableEndpoints):
        Publisher.publish(issued.subscription_id)
    assert Publisher.publish_for_node(ready_node.pk) == {"published": 0, "failed": 0}


@pytest.mark.django_db
def test_publishing_rejects_health_evidence_without_all_positive_controls(ready_node):
    _profile, issued, _credential = assigned_profile(ready_node, "incomplete-probe")
    NodeConfigRevision.objects.filter(node=ready_node).update(
        probe_result={
            "generation": ready_node.applied_generation,
            "app_health_passed": True,
            "accepted": True,
            "positive_control": True,
        }
    )

    with pytest.raises(NoPublishableEndpoints):
        Publisher.publish(issued.subscription_id)
    assert Publisher.publish_for_node(ready_node.pk) == {"published": 0, "failed": 0}


@pytest.mark.django_db
def test_node_counts_count_distinct_ready_nodes_and_report_drift(ready_node):
    from apps.subscriptions.serializers import subscription_representation

    ready_node.pool.region_allocations.update(quota=1)
    _profile, issued, _credential = assigned_profile(ready_node, "counted")
    Publisher.publish(issued.subscription_id)
    subscription = TokenService.resolve(issued.raw_token)
    assert subscription_representation(subscription)["node_counts"] == {
        "expected": 1,
        "assigned": 1,
        "ready": 1,
        "published": 1,
        "mismatch": False,
    }
    ready_node.raw_cloud_state = "stopped"
    ready_node.save(update_fields=["raw_cloud_state", "updated_at"])
    assert subscription_representation(subscription)["node_counts"] == {
        "expected": 1,
        "assigned": 1,
        "ready": 0,
        "published": 1,
        "mismatch": True,
    }
    ready_node.consumes_quota = False
    ready_node.desired_state = "DELETED"
    ready_node.provisioning_state = "DELETED"
    ready_node.save(
        update_fields=["consumes_quota", "desired_state", "provisioning_state", "updated_at"]
    )
    assert subscription.profile.node_credentials.filter(revoked_at__isnull=True).exists()
    assert subscription_representation(subscription)["node_counts"] == {
        "expected": 1,
        "assigned": 0,
        "ready": 0,
        "published": 1,
        "mismatch": True,
    }


@pytest.mark.django_db
def test_node_counts_do_not_report_revoked_subscription_as_published(ready_node):
    from apps.subscriptions.serializers import subscription_representation

    ready_node.pool.region_allocations.update(quota=1)
    _profile, issued, _credential = assigned_profile(ready_node, "revoked-count")
    Publisher.publish(issued.subscription_id)
    TokenService.disable(issued.subscription_id)
    subscription = Subscription.objects.get(pk=issued.subscription_id)

    assert subscription_representation(subscription)["node_counts"] == {
        "expected": 1,
        "assigned": 1,
        "ready": 1,
        "published": 0,
        "mismatch": True,
    }


@pytest.mark.django_db
def test_node_counts_ignore_shared_scope_credentials(ready_node):
    from apps.subscriptions.serializers import subscription_representation

    ready_node.pool.region_allocations.update(quota=1)
    protocol = NodeProtocol.objects.create(
        node=ready_node,
        protocol="vless",
        port=18446,
        credential_scope="shared",
    )
    profile = AccessProfile.objects.create(name="shared-count")
    issued = TokenService.issue(profile.pk)
    credential = CredentialService.rotate(
        ready_node.pk,
        profile_ids=[profile.pk],
        protocol_ids=[protocol.pk],
    )[0]
    ready_node.refresh_from_db()
    ready_node.applied_generation = ready_node.desired_generation
    ready_node.save(update_fields=["applied_generation", "updated_at"])
    credential.applied_generation = credential.desired_generation
    credential.save(update_fields=["applied_generation"])
    trusted_health(ready_node)

    subscription = TokenService.resolve(issued.raw_token)

    assert subscription_representation(subscription)["node_counts"] == {
        "expected": 1,
        "assigned": 0,
        "ready": 0,
        "published": 0,
        "mismatch": True,
    }


@pytest.mark.django_db
def test_reconcile_new_node_assigns_only_live_subscriptions_once(ready_node):
    from apps.subscriptions.access import reconcile_node_for_active_subscriptions

    _profile, issued, _credential = assigned_profile(ready_node, "live-pool")
    Publisher.publish(issued.subscription_id)
    expired_profile = AccessProfile.objects.create(name="expired-token")
    expired = TokenService.issue(expired_profile.pk)
    SubscriptionToken.objects.filter(subscription_id=expired.subscription_id).update(status="EXPIRED")
    revoked_profile = AccessProfile.objects.create(name="revoked-token")
    revoked = TokenService.issue(revoked_profile.pk)
    TokenService.disable(revoked.subscription_id)
    new_node = ManagedNode.objects.get(pk=ready_node.pk)
    new_node.pk = uuid4()
    new_node.deterministic_name = f"new-{uuid4()}"
    new_node.operation_key = uuid4()
    new_node.desired_generation = new_node.applied_generation = 1
    new_node.save(force_insert=True)
    protocol = NodeProtocol.objects.create(node=new_node, protocol="vless", port=18444)
    trusted_health(new_node)

    first = reconcile_node_for_active_subscriptions(new_node.pk)
    second = reconcile_node_for_active_subscriptions(new_node.pk)

    assert first["scheduled"] == 1
    assert second["scheduled"] == 0
    assert NodeCredential.objects.filter(node=new_node, protocol=protocol).count() == 1
    assert set(
        NodeCredential.objects.filter(node=new_node).values_list("profile_id", flat=True)
    ) == {_profile.pk}
    assert (
        SubscriptionToken.objects.get(subscription_id=expired.subscription_id).status
        == "EXPIRED"
    )
    assert (
        SubscriptionToken.objects.get(subscription_id=revoked.subscription_id).status
        == "REVOKED"
    )


@pytest.mark.django_db
def test_reconcile_skips_expired_profile_with_active_token(ready_node):
    from apps.subscriptions.access import reconcile_node_for_active_subscriptions

    profile = AccessProfile.objects.create(
        name="expired-profile", expires_at=timezone.now() - timedelta(seconds=1)
    )
    issued = TokenService.issue(profile.pk)
    node = ManagedNode.objects.get(pk=ready_node.pk)
    node.desired_state = "PRESENT"
    node.provisioning_state = "READY"
    node.raw_cloud_state = "running"
    node.health_state = "HEALTHY"
    node.save(
        update_fields=[
            "desired_state",
            "provisioning_state",
            "raw_cloud_state",
            "health_state",
            "updated_at",
        ]
    )
    NodeProtocol.objects.create(node=node, protocol="vless", port=18445)
    trusted_health(node)

    result = reconcile_node_for_active_subscriptions(node.pk)

    assert result == {"scheduled": 0, "operation_ids": []}
    assert SubscriptionToken.objects.get(
        subscription_id=issued.subscription_id
    ).status == "ACTIVE"
    assert not NodeCredential.objects.filter(profile=profile, node=node).exists()
