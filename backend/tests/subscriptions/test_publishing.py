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
