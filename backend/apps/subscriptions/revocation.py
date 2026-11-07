from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager, suppress
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.nodes.bootstrap import _ClaimLease
from apps.nodes.models import ManagedNode, NodeConfigRevision
from apps.operations.claims import assert_current, claim_operation, release_claim
from apps.operations.models import Operation, OperationStep
from apps.operations.services import OperationService
from common.errors import DomainError

from .credentials import CredentialService, decrypt_material
from .models import (
    AccessProfile,
    NodeCredential,
    RevocationNodeState,
    Subscription,
    SubscriptionRevision,
)
from .publishing import Publisher
from .tokens import TokenService
from .verification import choose_node_outcome, verified_revoked


class RevocationService:
    def __init__(
        self,
        *,
        executor_factory: Callable | None = None,
        lifecycle_factory: Callable | None = None,
        invalidate_node: Callable[[UUID], object] | None = None,
    ):
        self.executor_factory = executor_factory or self._default_executor
        self.lifecycle_factory = lifecycle_factory or self._default_lifecycle
        self.invalidate_node = invalidate_node or Publisher.invalidate_node

    @staticmethod
    def _default_executor(node):
        from .revocation_runtime import default_executor

        return default_executor(node)

    @staticmethod
    @contextmanager
    def _fenced(claim):
        with transaction.atomic():
            Operation.objects.select_for_update().get(pk=claim.operation_id)
            assert_current(claim)
            yield

    @staticmethod
    def _default_lifecycle():
        from apps.nodes.lifecycle import NodeLifecycle

        return NodeLifecycle()

    @staticmethod
    def request(
        profile_id: UUID,
        *,
        key: UUID,
        preview_id: UUID,
        confirmation: str,
        admin,
        test_only_skip_runtime_preflight: bool = False,
    ) -> Operation:
        params = {"profile_id": str(profile_id), "confirmation": confirmation}
        existing = Operation.objects.filter(
            admin=admin,
            kind="subscription.revoke",
            target_id=profile_id,
            idempotency_key=key,
        ).first()
        if existing is not None:
            return OperationService.submit(
                kind="subscription.revoke",
                target_id=profile_id,
                params=params,
                key=key,
                preview_id=preview_id,
                admin=admin,
                target_type="access_profile",
            )

        with transaction.atomic():
            subscription = Subscription.objects.select_for_update().get(
                profile_id=profile_id
            )
            profile = AccessProfile.objects.select_for_update().get(pk=profile_id)
            if profile.status != "ACTIVE":
                raise DomainError(
                    "PROFILE_NOT_ACTIVE", "访问身份不是活动状态", status_code=409
                )
            if test_only_skip_runtime_preflight:
                if getattr(settings, "XRAY_ENV", "") != "test":
                    raise DomainError(
                        "TEST_ONLY_REVOCATION_BYPASS",
                        "仅测试环境可跳过撤回能力检查",
                        status_code=403,
                    )
            else:
                from .revocation_runtime import validate_request_profile

                validate_request_profile(profile)
            operation = OperationService.submit(
                kind="subscription.revoke",
                target_id=profile_id,
                params=params,
                key=key,
                preview_id=preview_id,
                admin=admin,
                target_type="access_profile",
            )
            if (
                operation.preview
                and operation.preview.snapshot.get("profile_status") != profile.status
            ):
                raise DomainError(
                    "PREVIEW_STALE", "访问身份状态已改变，请重新预览", status_code=409
                )

            operation.can_cancel = False
            operation.save(update_fields=["can_cancel", "updated_at"])
            TokenService.disable(subscription.pk)
            profile.status = "REVOKING"
            profile.publishing_frozen = True
            profile.save(update_fields=["status", "publishing_frozen", "updated_at"])
            if subscription.current_revision_id:
                SubscriptionRevision.objects.filter(
                    pk=subscription.current_revision_id, usable=True
                ).update(usable=False, invalidated_at=timezone.now())

            credentials = list(
                NodeCredential.objects.select_for_update()
                .filter(profile=profile, revoked_at__isnull=True)
                .order_by("node_id", "pk")
            )
            by_node: dict[UUID, list[str]] = {}
            for credential in credentials:
                by_node.setdefault(credential.node_id, []).append(str(credential.pk))
            for node_id, credential_refs in by_node.items():
                RevocationNodeState.objects.create(
                    operation=operation,
                    node_id=node_id,
                    credential_refs=credential_refs,
                )
                ManagedNode.objects.filter(pk=node_id).update(
                    security_state="REVOKING", updated_at=timezone.now()
                )
            return operation

    @staticmethod
    def _config_without_revoked(node: ManagedNode, revoked_refs: set[UUID]) -> dict:
        remaining = []
        from .access import active_node_credentials

        credentials = active_node_credentials(node, excluded_credential_refs=revoked_refs)
        for credential in credentials:
            remaining.append(
                {
                    "credential_ref": str(credential.pk),
                    "profile_id": str(credential.profile_id),
                    "protocol_id": str(credential.protocol_id),
                    "protocol": credential.protocol.protocol,
                    "material": decrypt_material(credential),
                }
            )
        return {"schema_version": 1, "credentials": remaining}

    @staticmethod
    def _quarantine_operation(operation: Operation, node: ManagedNode) -> Operation:
        key = uuid5(
            NAMESPACE_URL,
            f"xray:revocation:{operation.pk}:{node.pk}:quarantine",
        )
        child = OperationService.submit(
            kind="node.quarantine",
            target_id=node.pk,
            params={
                "region": node.region,
                "account_id": str(node.cloud_account_id),
                "ssh_source": "",
            },
            key=key,
            preview_id=None,
            admin=operation.admin,
            cloud_credential_version=node.cloud_credential_version,
        )
        if child.can_cancel:
            child.can_cancel = False
            child.save(update_fields=["can_cancel", "updated_at"])
        return child

    @staticmethod
    def _record_step(
        operation: Operation,
        *,
        node: ManagedNode,
        name: str,
        status: str,
        evidence: dict | None = None,
    ) -> None:
        now = timezone.now()
        attempt = OperationStep.objects.filter(
            operation=operation, name=name
        ).count() + 1
        OperationStep.objects.create(
            operation=operation,
            name=name,
            phase="security",
            status=status,
            attempt=attempt,
            result={"node_id": str(node.pk)},
            evidence=evidence or {},
            started_at=now,
            finished_at=now,
        )

    def _fail_closed(
        self, *, operation, state, node, error, claim, lease,
    ) -> None:
        with self._fenced(claim):
            lease.assert_current()
            try:
                self.invalidate_node(node.pk)
            except Exception:
                pass
        confirmed = False
        isolation_evidence = {}
        try:
            with self._fenced(claim):
                lease.assert_current()
                child = self._quarantine_operation(operation, node)
            result = lease.call(
                lambda: self.lifecycle_factory().quarantine(node.pk, operation_id=child.pk)
            )
            confirmed = result.confirmed
            isolation_evidence = result.evidence
        except Exception as isolation_error:
            lease.assert_current()
            isolation_evidence = {
                "error_code": getattr(isolation_error, "code", "ISOLATION_EXECUTION_FAILED")
            }
        outcome = choose_node_outcome(removed=False, isolation_confirmed=confirmed)
        with self._fenced(claim):
            lease.assert_current()
            ManagedNode.objects.filter(pk=node.pk).update(
                security_state=outcome, updated_at=timezone.now()
            )
            state.status = outcome
            state.last_error_code = getattr(error, "code", "REVOCATION_EXECUTION_FAILED")
            state.evidence = {"isolation": isolation_evidence}
            state.save(update_fields=["status", "last_error_code", "evidence", "updated_at"])

    def run(self, operation_id: UUID, *, worker_id: str | None = None) -> Operation:
        operation = Operation.objects.get(pk=operation_id)
        if operation.kind != "subscription.revoke":
            raise DomainError("OPERATION_KIND_UNSUPPORTED", "不是订阅撤销操作", status_code=400)
        if operation.status in Operation.TERMINAL_STATUSES:
            return operation
        claim = claim_operation(
            operation_id, worker_id=worker_id or f"revocation-{uuid4()}", lease_seconds=240
        )
        lease = _ClaimLease(claim, lease_seconds=240)
        try:
            lease.start()
            return self._run_claimed(operation, claim=claim, lease=lease)
        finally:
            lease.stop()
            # A stale worker must never clear the replacement worker's lease.
            with suppress(DomainError):
                with self._fenced(claim):
                    release_claim(claim)

    def _run_claimed(self, operation, *, claim, lease) -> Operation:
        with self._fenced(claim):
            lease.assert_current()
            operation.current_step = "revoke.node_credentials"
            operation.save(update_fields=["current_step", "updated_at"])
        states = list(
            RevocationNodeState.objects.filter(operation=operation)
            .select_related("node").order_by("created_at", "pk")
        )
        for state in states:
            lease.assert_current()
            if state.status == "VERIFIED_REVOKED":
                continue
            node = state.node
            refs = {UUID(value) for value in state.credential_refs}
            target_credentials = list(
                NodeCredential.objects.filter(
                    pk__in=refs, profile_id=operation.target_id,
                    node=node, revoked_at__isnull=True,
                ).order_by("pk")
            )
            executor = None
            try:
                executor = self.executor_factory(node)
                shared_protocol_ids = {
                    credential.protocol_id for credential in target_credentials
                    if credential.credential_scope == "shared"
                }
                removal_refs = set(refs)
                if shared_protocol_ids:
                    removal_refs.update(
                        NodeCredential.objects.filter(
                            node=node, protocol_id__in=shared_protocol_ids,
                            revoked_at__isnull=True,
                        ).values_list("pk", flat=True)
                    )
                removed_credentials = list(
                    NodeCredential.objects.filter(pk__in=removal_refs).order_by("pk")
                )
                session_evidence = lease.call(lambda: executor.capture_probe_sessions(
                    node.pk,
                    credential_refs=[credential.pk for credential in removed_credentials],
                    operation_id=operation.pk,
                ))
                if {str(ref) for ref in session_evidence} != {str(ref) for ref in removal_refs}:
                    raise DomainError(
                        "REVOCATION_UNCONFIRMED", "旧会话证据不完整", status_code=409
                    )
                with self._fenced(claim):
                    lease.assert_current()
                    self._record_step(
                        operation, node=node, name="security.capture_sessions", status="SUCCEEDED",
                        evidence={
                            "session_count": len(session_evidence),
                            "credential_count": len(removed_credentials),
                        },
                    )
                    replacements = []
                    active_profile_ids = list(
                        AccessProfile.objects.filter(status="ACTIVE").order_by("pk")
                        .values_list("pk", flat=True)
                    )
                    if shared_protocol_ids and active_profile_ids:
                        replacements = CredentialService.rotate(
                            node.pk, profile_ids=active_profile_ids,
                            protocol_ids=list(shared_protocol_ids),
                        )
                    locked_node = ManagedNode.objects.select_for_update().get(pk=node.pk)
                    if replacements:
                        generation = locked_node.desired_generation
                    else:
                        generation = max(
                            locked_node.desired_generation, locked_node.applied_generation
                        ) + 1
                        locked_node.desired_generation = generation
                    locked_node.security_state = "REVOKING"
                    locked_node.save(update_fields=[
                        "desired_generation", "security_state", "updated_at"
                    ])
                    state.target_generation = generation
                    state.status = "APPLYING"
                    state.save(update_fields=["target_generation", "status", "updated_at"])
                    config = self._config_without_revoked(node, removal_refs)
                apply_result = lease.call(lambda: executor.apply_config(
                    node.pk, generation=generation, config=config,
                    operation_id=operation.pk, allow_security_rollback=False, claim=claim,
                ))
                with self._fenced(claim):
                    lease.assert_current()
                    state.status = "SERVICE_RESTARTED"
                    state.save(update_fields=["status", "updated_at"])
                    self._record_step(
                        operation, node=node, name="security.apply_config", status="SUCCEEDED",
                        evidence={
                            "generation": generation,
                            "config_test_passed": apply_result.config_test_passed,
                            "service_restarted": apply_result.service_restarted,
                            "rollback_performed": apply_result.rollback_performed,
                        },
                    )
                probes = [
                    lease.call(lambda credential=credential: executor.probe(
                        node.pk, credential_ref=credential.pk,
                        expect_accept=False, operation_id=operation.pk,
                    ))
                    for credential in removed_credentials
                ]
                if not removed_credentials or not all(verified_revoked(probe) for probe in probes):
                    raise DomainError(
                        "REVOCATION_UNCONFIRMED", "撤销探测证据不完整", status_code=409
                    )
                with self._fenced(claim):
                    lease.assert_current()
                    self._record_step(
                        operation, node=node, name="security.verify_revocation", status="SUCCEEDED",
                        evidence={
                            "generation": generation, "rejected_old_credentials": len(probes),
                            "positive_controls": sum(1 for probe in probes if probe.positive_control),
                        },
                    )
                    now = timezone.now()
                    locked_node = ManagedNode.objects.select_for_update().get(pk=node.pk)
                    if (
                        locked_node.desired_generation != generation
                        or locked_node.applied_generation != generation
                    ):
                        raise DomainError(
                            "CONFIG_GENERATION_RACE",
                            "节点配置在撤回验证期间发生变化",
                            status_code=409,
                        )
                    NodeCredential.objects.filter(pk__in=removal_refs).update(revoked_at=now)
                    applied_refs = [UUID(item["credential_ref"]) for item in config["credentials"]]
                    NodeCredential.objects.filter(pk__in=applied_refs).update(
                        desired_generation=generation, applied_generation=generation,
                    )
                    locked_node.security_state = "OPEN"
                    locked_node.save(update_fields=["security_state", "updated_at"])
                    NodeConfigRevision.objects.filter(
                        node=node, generation=generation, usable=True
                    ).update(
                        probe_result={
                            "generation": generation,
                            "app_health_passed": True,
                            "accepted": True,
                            "positive_control": True,
                            "fresh_connection": True,
                        }
                    )
                    state.status = "VERIFIED_REVOKED"
                    state.last_error_code = ""
                    state.evidence = {
                        "generation": generation,
                        "verified_credentials": [str(value.pk) for value in removed_credentials],
                    }
                    state.save(update_fields=["status", "last_error_code", "evidence", "updated_at"])
            except Exception as exc:
                # This also catches a fence lost during a failing external call.
                # Such a worker cannot launch quarantine or finalize node state.
                lease.assert_current()
                self._fail_closed(
                    operation=operation, state=state, node=node, error=exc,
                    claim=claim, lease=lease,
                )
            finally:
                if executor is not None:
                    with suppress(Exception):
                        close = getattr(executor, "close", None)
                        if callable(close):
                            close()

        with self._fenced(claim):
            lease.assert_current()
            operation = Operation.objects.select_for_update().get(pk=operation.pk)
            profile = AccessProfile.objects.select_for_update().get(pk=operation.target_id)
            all_verified = all(
                state.status == "VERIFIED_REVOKED"
                for state in RevocationNodeState.objects.filter(operation=operation)
            )
            if all_verified:
                profile.status = "REVOKED"
                profile.revoked_at = timezone.now()
                profile.save(update_fields=["status", "revoked_at", "updated_at"])
                operation.status = "SUCCEEDED"
                operation.error_code = ""
            else:
                operation.status = "PARTIALLY_SUCCEEDED"
                operation.error_code = "REVOCATION_UNCONFIRMED"
            operation.current_step = "complete"
            operation.result = {
                "node_states": [
                    {
                        "node_id": str(node_state.node_id), "status": node_state.status,
                        "last_error_code": node_state.last_error_code,
                    }
                    for node_state in RevocationNodeState.objects.filter(operation=operation)
                    .order_by("node_id")
                ]
            }
            operation.save(update_fields=[
                "status", "current_step", "error_code", "result", "updated_at"
            ])
            return operation
