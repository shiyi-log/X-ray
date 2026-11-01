from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import SuperAdmin
from apps.nodes.models import ManagedNode
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


def _provisioned_node(node: ManagedNode) -> ManagedNode:
    node.external_id = f"fake-instance-{node.pk}"
    node.addresses = [{"value": "192.0.2.10", "family": 4, "kind": "dynamic"}]
    node.provisioning_state = "PROVISIONED"
    node.save(update_fields=["external_id", "addresses", "provisioning_state", "updated_at"])
    return node


def _reserved_node(cloud_account, *, pool=None) -> ManagedNode:
    from apps.nodes.models import NodePool
    from apps.nodes.quota import reserve_node

    if pool is None:
        pool = NodePool.objects.create(
            name=f"delete-pool-{uuid4()}", region="us-east-1", quota=3
        )
    return reserve_node(
        pool.pk,
        account_id=cloud_account.pk,
        region="us-east-1",
        plan_id="nano",
        image_id="debian-12",
        operation_key=uuid4(),
    )


def _node_delete_preview(client: APIClient, node: ManagedNode):
    return client.post(
        "/api/v1/operations/previews/",
        {"kind": "node.delete", "target_id": str(node.pk), "params": {}},
        format="json",
    )


def _submit_node_delete(
    client: APIClient,
    node: ManagedNode,
    *,
    preview_id: str,
    confirmation: str = "确认删除服务器",
    key: str | None = None,
):
    headers = {"HTTP_IDEMPOTENCY_KEY": key} if key is not None else {}
    return client.post(
        f"/api/v1/nodes/{node.pk}/actions/delete/",
        {"preview_id": preview_id, "confirmation": confirmation},
        format="json",
        **headers,
    )


def _submit_node_action(client: APIClient, node: ManagedNode, action: str):
    payload = {}
    if action == "delete":
        payload = {"preview_id": str(uuid4()), "confirmation": "确认删除服务器"}
    return client.post(
        f"/api/v1/nodes/{node.pk}/actions/{action}/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )


@pytest.mark.django_db
def test_secret_delivery_is_returned_once_and_never_retrievable(recent_admin_client):
    client, _admin = recent_admin_client
    profile = AccessProfile.objects.create(name="one-time-device")

    issued = client.post(
        f"/api/v1/access-profiles/{profile.pk}/subscription/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert issued.status_code == 201
    body = issued.json()
    assert body["display_once"] is True
    assert len(body["token"]) == 43
    assert body["url"] == f"http://testserver/s/{body['token']}"
    assert "?" not in body["url"]
    assert "urls" not in body

    repeated = client.post(
        f"/api/v1/access-profiles/{profile.pk}/subscription/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
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
    current_token = SubscriptionToken.objects.get(token_digest=profile.subscription.token_digest)
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


@pytest.mark.django_db
def test_token_revoke_is_target_bound_idempotent_and_keeps_other_tokens_active(
    recent_admin_client,
):
    client, _admin = recent_admin_client
    first_profile = AccessProfile.objects.create(name="token-revoke-first")
    second_profile = AccessProfile.objects.create(name="token-revoke-second")
    first = TokenService.issue(first_profile.pk)
    second = TokenService.issue(second_profile.pk)
    first_token = SubscriptionToken.objects.get(subscription_id=first.subscription_id)
    second_token = SubscriptionToken.objects.get(subscription_id=second.subscription_id)

    preview = client.post(
        "/api/v1/operations/previews/",
        {
            "kind": "subscription.token_revoke",
            "target_id": str(first_token.pk),
            "params": {
                "subscription_id": str(first.subscription_id),
                "token_id": str(first_token.pk),
            },
        },
        format="json",
    )
    assert preview.status_code == 201
    preview_body = preview.json()
    assert preview_body["required_phrase"] == "确认撤销令牌"

    key = str(uuid4())
    path = (
        f"/api/v1/subscriptions/{first.subscription_id}/tokens/"
        f"{first_token.pk}/revoke/"
    )
    response = client.post(
        path,
        {"preview_id": preview_body["id"], "confirmation": preview_body["required_phrase"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "REVOKED"
    assert body["is_current"] is False
    assert first.raw_token not in response.content.decode()
    assert client.get(f"/api/v1/subscriptions/{first.subscription_id}/tokens/").json()["items"][0]["status"] == "REVOKED"
    assert client.get("/api/v1/subscriptions/").json()["items"][0]["current_token_status"] == "REVOKED"
    with pytest.raises(TokenGone):
        TokenService.resolve(first.raw_token)
    assert TokenService.resolve(second.raw_token).pk == second.subscription_id
    assert client.post(
        path,
        {"preview_id": preview_body["id"], "confirmation": preview_body["required_phrase"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    ).json() == body
    assert second_token.status == "ACTIVE"


@pytest.mark.django_db
def test_token_revoke_requires_preview_and_recent_step_up(recent_admin_client):
    client, _admin = recent_admin_client
    profile = AccessProfile.objects.create(name="token-revoke-guard")
    issued = TokenService.issue(profile.pk)
    token = SubscriptionToken.objects.get(subscription_id=issued.subscription_id)
    path = f"/api/v1/subscriptions/{issued.subscription_id}/tokens/{token.pk}/revoke/"

    missing_preview = client.post(
        path,
        {"confirmation": "确认撤销令牌"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert missing_preview.status_code == 409
    assert missing_preview.json()["code"] == "PREVIEW_REQUIRED"

    preview = client.post(
        "/api/v1/operations/previews/",
        {
            "kind": "subscription.token_revoke",
            "target_id": str(token.pk),
            "params": {"subscription_id": str(issued.subscription_id), "token_id": str(token.pk)},
        },
        format="json",
    ).json()
    session = client.session
    session["recent_auth_until"] = (timezone.now() - timedelta(seconds=1)).isoformat()
    session.save()
    stale = client.post(
        path,
        {"preview_id": preview["id"], "confirmation": preview["required_phrase"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert stale.status_code == 403
    assert stale.json()["code"] == "STEP_UP_REQUIRED"


@pytest.mark.django_db
def test_node_delete_preview_binds_identity_and_accepts_confirmed_operation(
    recent_admin_client, cloud_account
):
    client, _admin = recent_admin_client
    node = _reserved_node(cloud_account)
    _provisioned_node(node)

    preview_response = _node_delete_preview(client, node)
    assert preview_response.status_code == 201
    preview_body = preview_response.json()
    assert preview_body["kind"] == "node.delete"
    assert preview_body["required_phrase"] == "确认删除服务器"
    assert preview_body["snapshot"] == {
        "external_id": node.external_id,
        "region": node.region,
        "account_id": str(node.cloud_account_id),
        "addresses": node.addresses,
        "desired_state": node.desired_state,
        "desired_generation": node.desired_generation,
    }

    key = str(uuid4())
    response = _submit_node_delete(
        client, node, preview_id=preview_body["id"], key=key
    )
    assert response.status_code == 202
    operation = Operation.objects.get(pk=response.json()["operation_id"])
    assert operation.kind == "node.delete"
    assert operation.target_id == node.pk
    assert operation.params == {
        "region": node.region,
        "account_id": str(node.cloud_account_id),
        "confirmation": "确认删除服务器",
    }
    assert str(operation.idempotency_key) == key
    assert str(operation.preview_id) == preview_body["id"]
    assert operation.preview.consumed_at is not None
    assert ManagedNode.objects.get(pk=node.pk).consumes_quota is True


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["start", "reboot", "delete"])
@pytest.mark.parametrize("state", ["unprovisioned", "deleted"])
def test_node_cloud_actions_reject_unavailable_instances(
    recent_admin_client, cloud_account, action, state
):
    client, _admin = recent_admin_client
    node = _reserved_node(cloud_account)
    if state == "deleted":
        _provisioned_node(node)
        node.desired_state = "DELETED"
        node.save(update_fields=["desired_state", "updated_at"])

    response = _submit_node_action(client, node, action)

    assert response.status_code == 409
    assert response.json()["code"] == "NODE_NOT_PROVISIONED"
    assert not Operation.objects.filter(kind=f"node.{action}", target_id=node.pk).exists()


@pytest.mark.django_db
def test_node_delete_requires_preview_confirmation_recent_step_up_and_uuid_key(
    recent_admin_client, cloud_account
):
    client, _admin = recent_admin_client
    node = _reserved_node(cloud_account)
    _provisioned_node(node)
    key = str(uuid4())

    missing_preview = client.post(
        f"/api/v1/nodes/{node.pk}/actions/delete/",
        {"confirmation": "确认删除服务器"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )
    assert missing_preview.status_code == 409
    assert missing_preview.json()["code"] == "PREVIEW_REQUIRED"

    preview = _node_delete_preview(client, node).json()
    missing_key = _submit_node_delete(client, node, preview_id=preview["id"])
    assert missing_key.status_code == 400
    invalid_key = _submit_node_delete(
        client, node, preview_id=preview["id"], key="not-a-uuid"
    )
    assert invalid_key.status_code == 400
    wrong_confirmation = _submit_node_delete(
        client, node, preview_id=preview["id"], confirmation="删除服务器", key=key
    )
    assert wrong_confirmation.status_code == 409
    assert wrong_confirmation.json()["code"] == "CONFIRMATION_MISMATCH"

    session = client.session
    session["recent_auth_until"] = (timezone.now() - timedelta(seconds=1)).isoformat()
    session.save()
    stale_step_up = _submit_node_delete(
        client, node, preview_id=preview["id"], key=str(uuid4())
    )
    assert stale_step_up.status_code == 403
    assert stale_step_up.json()["code"] == "STEP_UP_REQUIRED"
    assert not Operation.objects.filter(kind="node.delete", target_id=node.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("mutation", ["expired", "state_changed"])
def test_node_delete_rejects_expired_or_stale_snapshot(
    recent_admin_client, cloud_account, mutation
):
    client, _admin = recent_admin_client
    node = _reserved_node(cloud_account)
    _provisioned_node(node)
    preview_body = _node_delete_preview(client, node).json()
    preview = ActionPreview.objects.get(pk=preview_body["id"])
    if mutation == "expired":
        preview.expires_at = timezone.now() - timedelta(seconds=1)
        preview.save(update_fields=["expires_at"])
        expected_code = "PREVIEW_EXPIRED"
    else:
        node.refresh_from_db()
        node.desired_state = "STOPPED"
        node.save(update_fields=["desired_state", "updated_at"])
        expected_code = "PREVIEW_STALE"

    response = _submit_node_delete(
        client, node, preview_id=preview_body["id"], key=str(uuid4())
    )
    assert response.status_code == 409
    assert response.json()["code"] == expected_code
    assert not Operation.objects.filter(kind="node.delete", target_id=node.pk).exists()


@pytest.mark.django_db
def test_node_delete_preview_cannot_be_reused_for_another_node(
    recent_admin_client, cloud_account
):
    client, _admin = recent_admin_client
    node = _reserved_node(cloud_account)
    _provisioned_node(node)
    other = _reserved_node(cloud_account, pool=node.pool)
    _provisioned_node(other)
    preview = _node_delete_preview(client, node).json()

    response = _submit_node_delete(
        client, other, preview_id=preview["id"], key=str(uuid4())
    )
    assert response.status_code == 409
    assert response.json()["code"] == "PREVIEW_BINDING_MISMATCH"
    assert not Operation.objects.filter(kind="node.delete", target_id=other.pk).exists()


@pytest.mark.django_db
def test_node_delete_idempotency_key_replays_same_request_and_rejects_changed_request(
    recent_admin_client, cloud_account
):
    client, _admin = recent_admin_client
    node = _reserved_node(cloud_account)
    _provisioned_node(node)
    preview = _node_delete_preview(client, node).json()
    key = str(uuid4())

    first = _submit_node_delete(client, node, preview_id=preview["id"], key=key)
    replay = _submit_node_delete(client, node, preview_id=preview["id"], key=key)
    conflict = _submit_node_delete(
        client,
        node,
        preview_id=preview["id"],
        confirmation="其他确认",
        key=key,
    )
    assert first.status_code == replay.status_code == 202
    assert replay.json()["operation_id"] == first.json()["operation_id"]
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert Operation.objects.filter(kind="node.delete", target_id=node.pk).count() == 1
