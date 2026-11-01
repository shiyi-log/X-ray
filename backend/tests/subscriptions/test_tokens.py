import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import connections

from common.errors import DomainError


@pytest.mark.django_db(transaction=True)
def test_rotation_rejects_old_url_and_retains_only_digest():
    from apps.subscriptions.models import AccessProfile, Subscription, SubscriptionToken
    from apps.subscriptions.tokens import TokenGone, TokenService

    profile = AccessProfile.objects.create(name="phone", status="ACTIVE")
    old = TokenService.issue(profile.id)
    new = TokenService.rotate(old.subscription_id)

    assert old.raw_token != new.raw_token
    assert len(new.raw_token) >= 43
    with pytest.raises(TokenGone):
        TokenService.resolve(old.raw_token)
    assert TokenService.resolve(new.raw_token).pk == old.subscription_id
    row = Subscription.objects.get(pk=old.subscription_id)
    persisted = repr(row.__dict__) + repr(list(SubscriptionToken.objects.values()))
    assert old.raw_token not in persisted
    assert new.raw_token not in persisted


@pytest.mark.django_db(transaction=True)
def test_concurrent_rotation_serializes_and_only_last_token_resolves():
    from apps.subscriptions.models import AccessProfile
    from apps.subscriptions.tokens import TokenGone, TokenService

    profile = AccessProfile.objects.create(name="tablet", status="ACTIVE")
    issued = TokenService.issue(profile.pk)
    barrier = Barrier(2)

    def rotate():
        connections.close_all()
        barrier.wait(timeout=5)
        try:
            return TokenService.rotate(issued.subscription_id).raw_token
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        tokens = list(executor.map(lambda _value: rotate(), range(2)))

    outcomes = []
    for token in tokens:
        try:
            TokenService.resolve(token)
            outcomes.append("active")
        except TokenGone:
            outcomes.append("gone")
    assert sorted(outcomes) == ["active", "gone"]


@pytest.mark.django_db
def test_issue_is_one_time_and_rejects_revoking_profile():
    from apps.subscriptions.models import AccessProfile
    from apps.subscriptions.tokens import TokenService

    profile = AccessProfile.objects.create(name="laptop", status="ACTIVE")
    TokenService.issue(profile.pk)
    with pytest.raises(DomainError) as caught:
        TokenService.issue(profile.pk)
    assert caught.value.code == "SECRET_ALREADY_DELIVERED"

    profile.status = "REVOKING"
    profile.save(update_fields=["status", "updated_at"])
    with pytest.raises(DomainError) as caught:
        TokenService.rotate(profile.subscription.pk)
    assert caught.value.code == "PROFILE_NOT_ACTIVE"


def test_malformed_token_is_unknown_without_echoing_input():
    from apps.subscriptions.tokens import TokenService, TokenUnknown

    raw = "not/a/valid/token"
    with pytest.raises(TokenUnknown) as caught:
        TokenService.resolve(raw)
    assert raw not in str(caught.value)


@pytest.mark.django_db
def test_recovery_inconsistent_revoked_token_fails_closed_without_tombstone():
    from apps.subscriptions.models import AccessProfile, SubscriptionToken
    from apps.subscriptions.tokens import TokenGone, TokenService

    profile = AccessProfile.objects.create(name="inconsistent-revocation")
    issued = TokenService.issue(profile.pk)
    token = SubscriptionToken.objects.get(subscription_id=issued.subscription_id)
    token.status = "REVOKED"
    token.save(update_fields=["status"])

    with pytest.raises(TokenGone):
        TokenService.resolve(issued.raw_token)


@pytest.mark.django_db
def test_token_digest_collision_fails_without_recursive_retry(monkeypatch):
    from apps.subscriptions import tokens
    from apps.subscriptions.models import AccessProfile
    from apps.subscriptions.tokens import TokenService

    first_profile = AccessProfile.objects.create(name="collision-source")
    first = TokenService.issue(first_profile.pk)
    calls = 0

    def colliding_token():
        nonlocal calls
        calls += 1
        if calls > 1:
            raise AssertionError("token issue retried recursively")
        return first.raw_token, hashlib.sha256(first.raw_token.encode("ascii")).hexdigest()

    monkeypatch.setattr(tokens, "_fresh_token", colliding_token)
    second_profile = AccessProfile.objects.create(name="collision-target")
    with pytest.raises(DomainError) as caught:
        TokenService.issue(second_profile.pk)
    assert caught.value.code == "SECRET_ALREADY_DELIVERED"
    assert calls == 1


@pytest.mark.django_db(transaction=True)
def test_tokens_use_one_pool_and_revoke_independently():
    from apps.subscriptions.models import AccessProfile, SubscriptionPool, SubscriptionToken
    from apps.subscriptions.tokens import TokenGone, TokenService

    first_profile = AccessProfile.objects.create(name="first-token")
    second_profile = AccessProfile.objects.create(name="second-token")
    first = TokenService.issue(first_profile.pk)
    second = TokenService.issue(second_profile.pk)

    first_subscription = TokenService.resolve(first.raw_token)
    second_subscription = TokenService.resolve(second.raw_token)
    assert first_subscription.pool_id == second_subscription.pool_id
    assert SubscriptionPool.objects.count() == 1

    first_token = SubscriptionToken.objects.get(subscription_id=first.subscription_id)
    TokenService.revoke_token(first.subscription_id, first_token.pk)
    with pytest.raises(TokenGone):
        TokenService.resolve(first.raw_token)
    assert TokenService.resolve(second.raw_token).pk == second.subscription_id


@pytest.mark.django_db(transaction=True)
def test_concurrent_token_revoke_and_rotation_use_consistent_lock_order():
    from apps.subscriptions.models import AccessProfile, SubscriptionToken
    from apps.subscriptions.tokens import TokenGone, TokenService

    profile = AccessProfile.objects.create(name="revoke-and-rotate")
    issued = TokenService.issue(profile.pk)
    token = SubscriptionToken.objects.get(subscription_id=issued.subscription_id)
    barrier = Barrier(2)

    def revoke():
        connections.close_all()
        barrier.wait(timeout=5)
        try:
            TokenService.revoke_token(issued.subscription_id, token.pk)
        finally:
            connections.close_all()

    def rotate():
        connections.close_all()
        barrier.wait(timeout=5)
        try:
            return TokenService.rotate(issued.subscription_id).raw_token
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        revoked = executor.submit(revoke)
        rotated = executor.submit(rotate)
        revoked.result(timeout=10)
        replacement = rotated.result(timeout=10)

    with pytest.raises(TokenGone):
        TokenService.resolve(issued.raw_token)
    assert TokenService.resolve(replacement).pk == issued.subscription_id
    tokens = list(
        SubscriptionToken.objects.filter(subscription_id=issued.subscription_id)
        .order_by("token_epoch")
        .values_list("token_epoch", "status")
    )
    assert tokens == [(1, "REVOKED"), (2, "ACTIVE")]


@pytest.mark.django_db(transaction=True)
def test_concurrent_token_revoke_and_subscription_disable_serialize():
    from apps.subscriptions.models import AccessProfile, Subscription, SubscriptionToken
    from apps.subscriptions.tokens import TokenGone, TokenService

    profile = AccessProfile.objects.create(name="revoke-and-disable")
    issued = TokenService.issue(profile.pk)
    token = SubscriptionToken.objects.get(subscription_id=issued.subscription_id)
    barrier = Barrier(2)

    def revoke_token():
        connections.close_all()
        barrier.wait(timeout=5)
        try:
            TokenService.revoke_token(issued.subscription_id, token.pk)
        finally:
            connections.close_all()

    def disable_subscription():
        connections.close_all()
        barrier.wait(timeout=5)
        try:
            TokenService.disable(issued.subscription_id)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        revoked = executor.submit(revoke_token)
        disabled = executor.submit(disable_subscription)
        revoked.result(timeout=10)
        disabled.result(timeout=10)

    subscription = Subscription.objects.get(pk=issued.subscription_id)
    token.refresh_from_db()
    assert subscription.status == "REVOKED"
    assert token.status == "REVOKED"
    with pytest.raises(TokenGone):
        TokenService.resolve(issued.raw_token)


@pytest.mark.django_db
def test_rotation_preserves_individual_revocation_timestamp_and_tombstone_reason():
    from apps.subscriptions.models import (
        AccessProfile,
        RevocationTombstone,
        SubscriptionToken,
    )
    from apps.subscriptions.tokens import TokenService

    profile = AccessProfile.objects.create(name="revoked-then-rotated")
    issued = TokenService.issue(profile.pk)
    token = SubscriptionToken.objects.get(subscription_id=issued.subscription_id)
    TokenService.revoke_token(issued.subscription_id, token.pk)
    token.refresh_from_db()
    tombstone = RevocationTombstone.objects.get(token_digest=token.token_digest)
    original_revoked_at = tombstone.revoked_at

    TokenService.rotate(issued.subscription_id)

    token.refresh_from_db()
    tombstone.refresh_from_db()
    assert token.revoked_at == original_revoked_at
    assert tombstone.revoked_at == original_revoked_at
    assert tombstone.reason == "token-revoked"
    assert token.replaced_by_id is not None
