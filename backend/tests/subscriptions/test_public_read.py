from uuid import uuid4

import pytest
from django.test import Client, override_settings


def publish_payload(subscription, body=b"subscription-body"):
    from apps.subscriptions.models import SubscriptionRevision
    from common.crypto import configured_secret_store

    revision_id = uuid4()
    number = 1
    envelope = configured_secret_store().encrypt(
        body,
        purpose="subscription.payload",
        aad=f"revision:{revision_id}:{number}:clash".encode(),
    )
    revision = SubscriptionRevision.objects.create(
        id=revision_id,
        subscription=subscription,
        number=number,
        public_version="public-v1",
        payloads={"clash": envelope},
        payload_hashes={},
        node_versions={},
        usable=True,
    )
    subscription.current_revision = revision
    subscription.save(update_fields=["current_revision", "updated_at"])
    return revision


@pytest.mark.django_db(transaction=True)
@override_settings(ROOT_URLCONF="config.subscription_urls")
def test_revoked_link_is_gone_before_revision_lookup():
    from apps.subscriptions.models import AccessProfile
    from apps.subscriptions.tokens import TokenService

    profile = AccessProfile.objects.create(name="temporary", status="ACTIVE")
    issued = TokenService.issue(profile.id)
    TokenService.disable(issued.subscription_id)
    client = Client()
    for method in (client.get, client.head):
        response = method(f"/s/{issued.raw_token}?format=clash")
        assert response.status_code == 410
        assert response["Cache-Control"] == "no-store"
        if method == client.head:
            assert response.content == b""


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="config.subscription_urls")
def test_unknown_and_gone_responses_have_equal_length():
    from apps.subscriptions.models import AccessProfile
    from apps.subscriptions.tokens import TokenService

    profile = AccessProfile.objects.create(name="equal-errors", status="ACTIVE")
    issued = TokenService.issue(profile.pk)
    TokenService.disable(issued.subscription_id)
    client = Client()
    gone = client.get(f"/s/{issued.raw_token}")
    unknown = client.get("/s/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    assert gone.status_code == 410
    assert unknown.status_code == 404
    assert len(gone.content) == len(unknown.content)


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="config.subscription_urls")
def test_reader_returns_only_current_usable_revision_and_ignores_v_parameter():
    from apps.subscriptions.models import AccessProfile
    from apps.subscriptions.tokens import TokenService

    profile = AccessProfile.objects.create(name="reader", status="ACTIVE")
    issued = TokenService.issue(profile.pk)
    subscription = TokenService.resolve(issued.raw_token)
    publish_payload(subscription, b"current-payload")

    response = Client().get(
        f"/s/{issued.raw_token}?format=clash&v=historical-version"
    )
    assert response.status_code == 200
    assert response.content == b"current-payload"
    assert response["Cache-Control"] == "no-store"


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="config.subscription_urls")
def test_maintenance_blocks_active_token_but_never_masks_revoked_token():
    from apps.subscriptions.models import AccessProfile
    from apps.subscriptions.security_barrier import SecurityBarrier
    from apps.subscriptions.tokens import TokenService

    active_profile = AccessProfile.objects.create(name="active", status="ACTIVE")
    active = TokenService.issue(active_profile.pk)
    publish_payload(TokenService.resolve(active.raw_token))
    revoked_profile = AccessProfile.objects.create(name="revoked", status="ACTIVE")
    revoked = TokenService.issue(revoked_profile.pk)
    TokenService.disable(revoked.subscription_id)
    SecurityBarrier.enter_restore()

    client = Client()
    assert client.get(f"/s/{active.raw_token}?format=clash").status_code == 503
    assert client.get(f"/s/{revoked.raw_token}?format=clash").status_code == 410


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="config.subscription_urls")
def test_valid_token_without_revision_is_service_unavailable():
    from apps.subscriptions.models import AccessProfile
    from apps.subscriptions.tokens import TokenService

    profile = AccessProfile.objects.create(name="not-ready", status="ACTIVE")
    issued = TokenService.issue(profile.pk)
    response = Client().get(f"/s/{issued.raw_token}?format=clash")
    assert response.status_code == 503
    assert response["Cache-Control"] == "no-store"


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="config.subscription_urls")
def test_canonical_url_defaults_to_mihomo_and_includes_published_nodes(
    publishable_subscription,
):
    from apps.subscriptions.publishing import Publisher

    issued, subscription, _node, _credential = publishable_subscription
    Publisher.publish(subscription.pk)

    response = Client().get(f"/s/{issued.raw_token}")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/yaml")
    assert b"proxies:" in response.content
