import base64
from copy import deepcopy

import pytest
from django.core.exceptions import ValidationError


@pytest.mark.django_db
def test_publish_creates_immutable_four_format_revision_without_rotating_token(
    publishable_subscription,
):
    from apps.subscriptions.models import SubscriptionRevision
    from apps.subscriptions.publishing import Publisher
    from apps.subscriptions.tokens import TokenService

    issued, subscription, _node, _credential = publishable_subscription
    token_epoch = subscription.token_epoch
    revision = Publisher.publish(subscription.pk)
    subscription.refresh_from_db()
    assert subscription.current_revision_id == revision.pk
    assert subscription.token_epoch == token_epoch
    assert set(revision.payloads) == {"shadowrocket", "clash", "mihomo", "v2ray"}
    assert TokenService.resolve(issued.raw_token).pk == subscription.pk

    revision.payloads = deepcopy(revision.payloads)
    revision.payloads["clash"] = {"tampered": True}
    with pytest.raises(ValidationError):
        revision.save()
    assert SubscriptionRevision.objects.get(pk=revision.pk).usable is True


@pytest.mark.django_db
def test_revision_ciphertext_is_bound_to_format_and_revision(publishable_subscription):
    from apps.subscriptions.publishing import Publisher, decrypt_payload

    _issued, subscription, _node, _credential = publishable_subscription
    revision = Publisher.publish(subscription.pk)
    clash = decrypt_payload(revision, "clash")
    assert b"proxies:" in clash
    swapped = deepcopy(revision.payloads)
    swapped["clash"] = revision.payloads["mihomo"]
    revision.payloads = swapped
    with pytest.raises(ValueError):
        decrypt_payload(revision, "clash")


@pytest.mark.django_db
def test_non_ready_or_unapplied_node_is_not_published(publishable_subscription):
    from apps.subscriptions.publishing import NoPublishableEndpoints, Publisher

    _issued, subscription, node, _credential = publishable_subscription
    node.provisioning_state = "PROVISIONED"
    node.save(update_fields=["provisioning_state", "updated_at"])
    with pytest.raises(NoPublishableEndpoints):
        Publisher.publish(subscription.pk)


@pytest.mark.django_db
def test_publish_includes_each_ready_node_address(publishable_subscription):
    from apps.subscriptions.models import SubscriptionRevision
    from apps.subscriptions.publishing import Publisher, decrypt_payload

    _issued, subscription, node, _credential = publishable_subscription
    node.addresses = [
        {"value": "192.0.2.50", "family": 4, "kind": "static"},
        {"value": "2001:db8::50", "family": 6, "kind": "static"},
    ]
    node.save(update_fields=["addresses", "updated_at"])

    revision = Publisher.publish(subscription.pk)
    payload = base64.b64decode(decrypt_payload(revision, "shadowrocket")).decode()
    assert "192.0.2.50" in payload
    assert "[2001:db8::50]" in payload
    assert set(revision.node_versions) == {
        f"{node.pk}:{_credential.pk}:v4",
        f"{node.pk}:{_credential.pk}:v6",
    }
    assert SubscriptionRevision.objects.filter(pk=revision.pk, usable=True).exists()


@pytest.mark.django_db
def test_invalidate_node_fails_closed_when_no_alternative_endpoint(
    publishable_subscription,
):
    from apps.subscriptions.publishing import Publisher

    _issued, subscription, node, _credential = publishable_subscription
    revision = Publisher.publish(subscription.pk)
    batch = Publisher.invalidate_node(node.pk)
    revision.refresh_from_db()
    subscription.refresh_from_db()
    assert revision.usable is False
    assert subscription.current_revision_id == revision.pk
    assert batch.status == "PARTIALLY_SUCCEEDED"


@pytest.mark.django_db
def test_address_refresh_republishes_with_new_ip_and_invalidates_old_revision(
    publishable_subscription,
):
    from apps.subscriptions.publishing import Publisher, decrypt_payload

    _issued, subscription, node, _credential = publishable_subscription
    old_revision = Publisher.publish(subscription.pk)
    node.addresses = [{"value": "198.51.100.77", "family": 4, "kind": "dynamic"}]
    node.save(update_fields=["addresses", "updated_at"])

    result = Publisher.refresh_node_address(node.pk)

    old_revision.refresh_from_db()
    subscription.refresh_from_db()
    new_revision = subscription.current_revision
    payload = base64.b64decode(decrypt_payload(new_revision, "shadowrocket")).decode()
    assert result == {"published": 1, "failed": 0}
    assert old_revision.usable is False
    assert new_revision.pk != old_revision.pk
    assert new_revision.usable is True
    assert "198.51.100.77" in payload
    assert "192.0.2.50" not in payload


@pytest.mark.django_db
def test_address_refresh_keeps_stale_ip_unusable_if_new_revision_cannot_be_published(
    publishable_subscription,
):
    from apps.subscriptions.publishing import Publisher

    _issued, subscription, node, _credential = publishable_subscription
    old_revision = Publisher.publish(subscription.pk)
    node.addresses = []
    node.save(update_fields=["addresses", "updated_at"])

    result = Publisher.refresh_node_address(node.pk)

    old_revision.refresh_from_db()
    subscription.refresh_from_db()
    assert result == {"published": 0, "failed": 1}
    assert old_revision.usable is False
    assert subscription.current_revision_id == old_revision.pk
