from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import SuperAdmin
from apps.operations.models import ActionPreview, Operation
from apps.subscriptions.models import AccessProfile, SubscriptionToken
from apps.subscriptions.tokens import TokenGone, TokenService


@pytest.fixture
def recent_admin_client(db):
    admin = SuperAdmin.objects.create_superuser("safe-controls", "test-only-password")
    client = APIClient()
    session = client.session
    session["admin_id"] = str(admin.pk)
    session["session_version"] = admin.session_version
    session["absolute_expires_at"] = (timezone.now() + timedelta(hours=1)).isoformat()
    session["recent_auth_until"] = (timezone.now() + timedelta(minutes=5)).isoformat()
    session.save()
    return client, admin


def _preview(client: APIClient, profile: AccessProfile, *, params: dict | None = None):
    return client.post(
        "/api/v1/operations/previews/",
        {
            "kind": "subscription.revoke",
            "target_id": str(profile.pk),
            "params": params or {"profile_id": str(profile.pk)},
        },
        format="json",
    )


@pytest.mark.django_db
def test_secret_delivery_is_returned_once_and_never_retrievable(recent_admin_client):
    client, _admin = recent_admin_client
    profile = AccessProfile.objects.create(name="one-time-device")

    issued = client.post(
        f"/api/v1/access-profiles/{profile.pk}/subscription/", {}, format="json"
    )
    assert issued.status_code == 201
    body = issued.json()
    assert body["display_once"] is True
    assert len(body["token"]) == 43
    assert set(body["urls"]) == {"shadowrocket", "clash", "mihomo", "v2ray"}

    repeated = client.post(
        f"/api/v1/access-profiles/{profile.pk}/subscription/", {}, format="json"
    )
    assert repeated.status_code == 409
    assert repeated.json()["code"] == "SECRET_ALREADY_DELIVERED"
    assert body["token"] not in client.get("/api/v1/subscriptions/").content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("expired", "PREVIEW_EXPIRED"),
        ("params", "PREVIEW_STALE"),
        ("confirmation", "CONFIRMATION_MISMATCH"),
    ],
)
def test_force_revoke_revalidates_preview_and_confirmation(
    recent_admin_client, mutation, expected_code
):
    client, _admin = recent_admin_client
    profile = AccessProfile.objects.create(name=f"preview-{mutation}")
    TokenService.issue(profile.pk)
    preview_response = _preview(client, profile)
    assert preview_response.status_code == 201
    preview = ActionPreview.objects.get(pk=preview_response.json()["id"])
    if mutation == "expired":
        preview.expires_at = timezone.now() - timedelta(seconds=1)
        preview.save(update_fields=["expires_at"])

    payload = {
        "preview_id": str(preview.pk),
        "confirmation": "wrong" if mutation == "confirmation" else preview.required_phrase,
    }
    if mutation == "params":
        preview.params_hash = "0" * 64
        preview.save(update_fields=["params_hash"])

    response = client.post(
        f"/api/v1/access-profiles/{profile.pk}/force-revoke/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert response.status_code == 409
    assert response.json()["code"] == expected_code
    assert Operation.objects.filter(target_id=profile.pk).count() == 0


@pytest.mark.django_db
def test_force_revoke_disables_link_before_operation_and_cancel_cannot_restore_it(
    recent_admin_client,
):
    client, _admin = recent_admin_client
    profile = AccessProfile.objects.create(name="revoked-device")
    issued = TokenService.issue(profile.pk)
    preview = _preview(client, profile).json()

    response = client.post(
        f"/api/v1/access-profiles/{profile.pk}/force-revoke/",
        {"preview_id": preview["id"], "confirmation": preview["required_phrase"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert response.status_code == 202
    assert response.json()["link_revoked"] is True
    operation = Operation.objects.get(pk=response.json()["operation_id"])
    assert operation.can_cancel is False
    current_token = SubscriptionToken.objects.get(
        token_digest=profile.subscription.token_digest
    )
    assert current_token.status == "REVOKED"
    with pytest.raises(TokenGone):
        TokenService.resolve(issued.raw_token)

    cancelled = client.post(f"/api/v1/operations/{operation.pk}/cancel/", {}, format="json")
    assert cancelled.status_code == 409
    with pytest.raises(TokenGone):
        TokenService.resolve(issued.raw_token)


@pytest.mark.django_db
def test_force_revoke_requires_recent_step_up(recent_admin_client):
    client, _admin = recent_admin_client
    profile = AccessProfile.objects.create(name="stale-step-up")
    TokenService.issue(profile.pk)
    preview = _preview(client, profile).json()
    session = client.session
    session["recent_auth_until"] = (timezone.now() - timedelta(seconds=1)).isoformat()
    session.save()

    response = client.post(
        f"/api/v1/access-profiles/{profile.pk}/force-revoke/",
        {"preview_id": preview["id"], "confirmation": preview["required_phrase"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "STEP_UP_REQUIRED"
