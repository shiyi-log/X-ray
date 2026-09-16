from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import connections

from apps.nodes.execution_types import ApplyResult, ProbeResult


def test_timeout_without_positive_control_is_unconfirmed():
    from apps.subscriptions.verification import verified_revoked

    result = ProbeResult(
        accepted=False,
        positive_control=False,
        fresh_connection=True,
        existing_session_closed=True,
        evidence={"failure": "timeout"},
    )
    assert verified_revoked(result) is False


def test_verified_revocation_requires_new_handshake_and_old_session_close():
    from apps.subscriptions.verification import verified_revoked

    base = {
        "accepted": False,
        "positive_control": True,
        "fresh_connection": True,
        "existing_session_closed": True,
        "evidence": {"authentication": "rejected", "generation": 2},
    }
    assert verified_revoked(ProbeResult(**base)) is True
    for field, value in (
        ("accepted", None),
        ("accepted", True),
        ("fresh_connection", False),
        ("existing_session_closed", None),
    ):
        candidate = {**base, field: value}
        assert verified_revoked(ProbeResult(**candidate)) is False


class SuccessfulExecutor:
    def __init__(self):
        self.captured = []
        self.applied = []

    def capture_probe_sessions(self, node_id, *, credential_refs, operation_id):
        self.captured.extend(credential_refs)
        return {value: f"session-{value}" for value in credential_refs}

    def apply_config(
        self,
        node_id,
        *,
        generation,
        config,
        operation_id,
        allow_security_rollback=False,
    ):
        self.applied.append((node_id, generation, config, allow_security_rollback))
        return ApplyResult(generation, True, True, False)

    def probe(self, node_id, *, credential_ref, expect_accept, operation_id):
        return ProbeResult(
            accepted=False,
            positive_control=True,
            fresh_connection=True,
            existing_session_closed=True,
            evidence={
                "session_id": f"session-{credential_ref}",
                "authentication": "rejected",
                "generation": 2,
            },
        )


class ApplyingTransport:
    def apply(self, request):
        return {
            "ok": True,
            "applied_generation": request["generation"],
            "config_test_passed": True,
            "service_restarted": True,
            "rollback_performed": False,
        }


class FailingCaptureExecutor:
    def __init__(self):
        self.calls = 0

    def capture_probe_sessions(self, *args, **kwargs):
        from common.errors import DomainError

        self.calls += 1
        raise DomainError("SSH_UNAVAILABLE", "ssh unavailable", status_code=503)


class UnconfirmedIsolation:
    def quarantine(self, node_id, *, operation_id):
        from apps.nodes.execution_types import IsolationResult

        return IsolationResult(False, {"firewall_safe": False})


def make_preview(admin, profile, confirmation="REVOKE PROFILE"):
    from apps.operations.services import ActionPreviewService

    params = {"profile_id": str(profile.pk), "confirmation": confirmation}
    return ActionPreviewService.create(
        admin=admin,
        kind="subscription.revoke",
        target_id=profile.pk,
        params=params,
        snapshot={"profile_status": profile.status},
        required_phrase="REVOKE PROFILE",
    )


@pytest.mark.django_db
def test_request_atomically_revokes_link_and_creates_uncancellable_operation(
    admin, revocable_profile
):
    from apps.subscriptions.models import RevocationNodeState
    from apps.subscriptions.revocation import RevocationService
    from apps.subscriptions.tokens import TokenGone, TokenService

    issued, profile, node, _credential = revocable_profile
    preview = make_preview(admin, profile)
    operation = RevocationService.request(
        profile.pk,
        key=uuid4(),
        preview_id=preview.pk,
        confirmation="REVOKE PROFILE",
        admin=admin,
    )

    profile.refresh_from_db()
    assert profile.status == "REVOKING"
    assert profile.publishing_frozen is True
    assert operation.can_cancel is False
    assert operation.status == "PENDING"
    assert RevocationNodeState.objects.filter(
        operation=operation, node=node, status="REQUESTED"
    ).exists()
    with pytest.raises(TokenGone):
        TokenService.resolve(issued.raw_token)


@pytest.mark.django_db
def test_run_marks_profile_revoked_only_after_every_node_is_verified(
    admin, revocable_profile
):
    from apps.subscriptions.models import RevocationNodeState
    from apps.subscriptions.revocation import RevocationService

    _issued, profile, node, credential = revocable_profile
    preview = make_preview(admin, profile)
    operation = RevocationService.request(
        profile.pk,
        key=uuid4(),
        preview_id=preview.pk,
        confirmation="REVOKE PROFILE",
        admin=admin,
    )
    executor = SuccessfulExecutor()
    service = RevocationService(
        executor_factory=lambda _node: executor,
        lifecycle_factory=lambda: None,
        invalidate_node=lambda _node_id: None,
    )
    service.run(operation.pk)

    profile.refresh_from_db()
    operation.refresh_from_db()
    credential.refresh_from_db()
    state = RevocationNodeState.objects.get(operation=operation, node=node)
    assert state.status == "VERIFIED_REVOKED"
    assert profile.status == "REVOKED"
    assert credential.revoked_at is not None
    assert operation.status == "SUCCEEDED"
    assert executor.applied[0][3] is False
    assert list(operation.steps.values_list("name", flat=True)) == [
        "security.capture_sessions",
        "security.apply_config",
        "security.verify_revocation",
    ]


@pytest.mark.django_db
def test_real_node_executor_accepts_only_a_related_revocation_operation(
    admin, revocable_profile
):
    from apps.nodes.execution_types import ProbeResult
    from apps.nodes.executor import NodeExecutor
    from apps.subscriptions.revocation import RevocationService

    _issued, profile, node, _credential = revocable_profile
    preview = make_preview(admin, profile)
    operation = RevocationService.request(
        profile.pk,
        key=uuid4(),
        preview_id=preview.pk,
        confirmation="REVOKE PROFILE",
        admin=admin,
    )
    executor = NodeExecutor(
        transport_factory=lambda _node: ApplyingTransport(),
        session_runner=lambda _node, refs, _operation_id: {
            ref: f"session-{ref}" for ref in refs
        },
        probe_runner=lambda *_args: ProbeResult(
            False,
            True,
            True,
            True,
            {"authentication": "rejected"},
        ),
    )

    RevocationService(
        executor_factory=lambda _node: executor,
        lifecycle_factory=lambda: None,
        invalidate_node=lambda _node_id: None,
    ).run(operation.pk)

    operation.refresh_from_db()
    profile.refresh_from_db()
    assert operation.status == "SUCCEEDED"
    assert profile.status == "REVOKED"


@pytest.mark.django_db
def test_operation_handler_routes_subscription_revocation(
    admin, revocable_profile
):
    from apps.operations.handlers import handle_operation
    from apps.subscriptions.revocation import RevocationService

    _issued, profile, _node, _credential = revocable_profile
    preview = make_preview(admin, profile)
    operation = RevocationService.request(
        profile.pk,
        key=uuid4(),
        preview_id=preview.pk,
        confirmation="REVOKE PROFILE",
        admin=admin,
    )
    executor = SuccessfulExecutor()
    service = RevocationService(
        executor_factory=lambda _node: executor,
        lifecycle_factory=lambda: None,
        invalidate_node=lambda _node_id: None,
    )

    result = handle_operation(str(operation.pk), revocation_service=service)

    assert result == {"operation_id": str(operation.pk), "status": "SUCCEEDED"}


@pytest.mark.django_db
def test_shared_secret_revocation_rotates_survivors_and_removes_every_old_copy(
    admin, ready_node
):
    from apps.nodes.models import NodeProtocol
    from apps.subscriptions.credentials import CredentialService, decrypt_material
    from apps.subscriptions.models import AccessProfile, NodeCredential
    from apps.subscriptions.revocation import RevocationService
    from apps.subscriptions.tokens import TokenService

    protocol = NodeProtocol.objects.create(
        node=ready_node,
        protocol="shadowsocks",
        port=8443,
        method="aes-128-gcm",
        credential_scope="shared",
    )
    revoked_profile = AccessProfile.objects.create(name="shared-revoked")
    survivor = AccessProfile.objects.create(name="shared-survivor")
    TokenService.issue(revoked_profile.pk)
    old_credentials = CredentialService.rotate(
        ready_node.pk,
        profile_ids=[revoked_profile.pk],
        protocol_ids=[protocol.pk],
    )
    ready_node.refresh_from_db()
    ready_node.applied_generation = ready_node.desired_generation
    ready_node.save(update_fields=["applied_generation", "updated_at"])
    NodeCredential.objects.filter(pk__in=[value.pk for value in old_credentials]).update(
        applied_generation=ready_node.applied_generation
    )
    old_passwords = {decrypt_material(value)["password"] for value in old_credentials}
    assert len(old_passwords) == 1

    preview = make_preview(admin, revoked_profile)
    operation = RevocationService.request(
        revoked_profile.pk,
        key=uuid4(),
        preview_id=preview.pk,
        confirmation="REVOKE PROFILE",
        admin=admin,
    )
    executor = SuccessfulExecutor()
    RevocationService(
        executor_factory=lambda _node: executor,
        lifecycle_factory=lambda: None,
        invalidate_node=lambda _node_id: None,
    ).run(operation.pk)

    for old in old_credentials:
        old.refresh_from_db()
        assert old.revoked_at is not None
    replacement = NodeCredential.objects.get(
        profile=survivor,
        protocol=protocol,
        revoked_at__isnull=True,
    )
    assert decrypt_material(replacement)["password"] not in old_passwords
    assert replacement.applied_generation == replacement.desired_generation
    applied_credentials = executor.applied[0][2]["credentials"]
    assert {item["profile_id"] for item in applied_credentials} == {str(survivor.pk)}


@pytest.mark.django_db
def test_partial_two_node_revocation_retries_only_the_unverified_node(
    admin, revocable_profile
):
    from apps.nodes.models import NodeProtocol
    from apps.nodes.quota import reserve_node
    from apps.operations.models import OutboxEvent
    from apps.operations.services import OperationService
    from apps.subscriptions.credentials import CredentialService
    from apps.subscriptions.models import NodeCredential, RevocationNodeState
    from apps.subscriptions.revocation import RevocationService

    _issued, profile, first_node, _first_credential = revocable_profile
    second_key = uuid4()
    second_node = reserve_node(
        first_node.pool_id,
        account_id=first_node.cloud_account_id,
        region=first_node.region,
        plan_id=first_node.plan_id,
        image_id=first_node.image_id,
        operation_key=second_key,
    )
    second_node.provisioning_state = "READY"
    second_node.desired_generation = 1
    second_node.applied_generation = 1
    second_node.addresses = [
        {"value": "192.0.2.51", "family": 4, "kind": "static"}
    ]
    second_node.save(
        update_fields=[
            "provisioning_state",
            "desired_generation",
            "applied_generation",
            "addresses",
            "updated_at",
        ]
    )
    protocol = NodeProtocol.objects.create(
        node=second_node,
        protocol="trojan",
        port=443,
        tls_enabled=True,
        server_name="proxy-2.example.test",
        credential_scope="profile",
    )
    second_credential = CredentialService.rotate(
        second_node.pk,
        profile_ids=[profile.pk],
        protocol_ids=[protocol.pk],
    )[0]
    second_node.refresh_from_db()
    second_node.applied_generation = second_node.desired_generation
    second_node.save(update_fields=["applied_generation", "updated_at"])
    NodeCredential.objects.filter(pk=second_credential.pk).update(
        applied_generation=second_node.applied_generation
    )

    preview = make_preview(admin, profile)
    operation = RevocationService.request(
        profile.pk,
        key=uuid4(),
        preview_id=preview.pk,
        confirmation="REVOKE PROFILE",
        admin=admin,
    )
    first_executor = SuccessfulExecutor()
    second_failing = FailingCaptureExecutor()
    executors = {
        first_node.pk: first_executor,
        second_node.pk: second_failing,
    }
    service = RevocationService(
        executor_factory=lambda node: executors[node.pk],
        lifecycle_factory=UnconfirmedIsolation,
        invalidate_node=lambda _node_id: None,
    )
    service.run(operation.pk)

    operation.refresh_from_db()
    profile.refresh_from_db()
    assert operation.status == "PARTIALLY_SUCCEEDED"
    assert profile.status == "REVOKING"
    assert RevocationNodeState.objects.get(
        operation=operation, node=first_node
    ).status == "VERIFIED_REVOKED"
    assert RevocationNodeState.objects.get(
        operation=operation, node=second_node
    ).status == "REVOCATION_UNCONFIRMED"
    assert len(first_executor.applied) == 1

    second_success = SuccessfulExecutor()
    executors[second_node.pk] = second_success
    retried = OperationService.retry(operation.pk, admin=admin)
    assert retried.status == "RETRY_PENDING"
    assert OutboxEvent.objects.filter(
        operation=operation, delivered_at__isnull=True
    ).exists()
    service.run(operation.pk)

    operation.refresh_from_db()
    profile.refresh_from_db()
    assert operation.status == "SUCCEEDED"
    assert profile.status == "REVOKED"
    assert len(first_executor.applied) == 1
    assert len(second_success.applied) == 1


@pytest.mark.django_db(transaction=True)
def test_token_rotation_racing_force_revocation_never_reactivates_access(
    admin, revocable_profile
):
    from apps.identity.models import SuperAdmin
    from apps.subscriptions.models import SubscriptionToken
    from apps.subscriptions.revocation import RevocationService
    from apps.subscriptions.tokens import TokenGone, TokenService
    from common.errors import DomainError

    issued, profile, _node, _credential = revocable_profile
    preview = make_preview(admin, profile)
    gate = Barrier(2)

    def rotate():
        connections.close_all()
        gate.wait(timeout=5)
        try:
            return TokenService.rotate(issued.subscription_id).raw_token
        except DomainError:
            return None
        finally:
            connections.close_all()

    def revoke():
        connections.close_all()
        gate.wait(timeout=5)
        try:
            thread_admin = SuperAdmin.objects.get(pk=admin.pk)
            return RevocationService.request(
                profile.pk,
                key=uuid4(),
                preview_id=preview.pk,
                confirmation="REVOKE PROFILE",
                admin=thread_admin,
            ).pk
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        rotated_token, operation_id = executor.submit(rotate), executor.submit(revoke)
        rotated_token = rotated_token.result(timeout=10)
        operation_id = operation_id.result(timeout=10)

    assert operation_id is not None
    with pytest.raises(TokenGone):
        TokenService.resolve(issued.raw_token)
    if rotated_token is not None:
        with pytest.raises(TokenGone):
            TokenService.resolve(rotated_token)
    assert not SubscriptionToken.objects.filter(
        subscription_id=issued.subscription_id,
        status="ACTIVE",
    ).exists()
