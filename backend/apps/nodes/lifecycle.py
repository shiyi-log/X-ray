from __future__ import annotations

import os
import socket
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.operations.authorization import DatabaseWriteAuthorizer
from apps.operations.claims import Claim, assert_current, claim_operation
from apps.operations.models import Operation, OperationStep
from common.errors import DomainError
from providers.base import (
    AccountRef,
    CreateRequest,
    FirewallRule,
    MutationPermit,
    ResourceRef,
)
from providers.registry import build_write_provider

from .execution_types import IsolationResult
from .models import ManagedNode, NodeResource

UNSAFE_SECURITY_STATES = {
    "REVOKING",
    "REVOCATION_UNCONFIRMED",
    "ISOLATION_UNCONFIRMED",
    "QUARANTINED",
    "MAINTENANCE",
}


def _default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


class NodeLifecycle:
    def __init__(
        self,
        *,
        provider_factory=None,
        isolation_probe=None,
        worker_id: str | None = None,
    ):
        self.provider_factory = provider_factory or self._build_provider
        self.isolation_probe = isolation_probe or (lambda _node: {})
        self.worker_id = worker_id or _default_worker_id()

    @staticmethod
    def _build_provider(node: ManagedNode, authorizer):
        return build_write_provider(
            node.cloud_account_id,
            node.region,
            authorizer=authorizer,
            credential_version=node.cloud_credential_version.version,
        )

    def provider_for(self, node: ManagedNode, authorizer):
        return self.provider_factory(node, authorizer)

    @staticmethod
    def _account_ref(node: ManagedNode) -> AccountRef:
        return AccountRef(
            node.cloud_account_id,
            node.cloud_account.provider,
            node.cloud_account.external_account_id,
            node.cloud_credential_version.version,
        )

    @staticmethod
    def _request(node: ManagedNode, operation: Operation) -> CreateRequest:
        return CreateRequest(
            name=node.deterministic_name,
            region=node.region,
            plan_id=node.plan_id,
            image_id=node.image_id,
            tags={
                "xray-manager": "true",
                "xray-node": str(node.pk),
                "xray-operation": str(operation.idempotency_key),
            },
        )

    @staticmethod
    def _permit(
        node: ManagedNode,
        operation: Operation,
        claim: Claim,
        action: str,
        *,
        resource_id: str | None,
    ) -> MutationPermit:
        return MutationPermit(
            operation_id=operation.pk,
            operation_key=str(operation.idempotency_key),
            action=action,
            account_id=node.cloud_account_id,
            external_account_id=node.cloud_account.external_account_id,
            region=node.region,
            resource_id=resource_id,
            expires_at=timezone.now() + timedelta(minutes=2),
            fence=claim.fence,
        )

    @staticmethod
    def _ensure_scope(node: ManagedNode, operation: Operation) -> None:
        if operation.target_id != node.pk or operation.target_type != "node":
            raise DomainError(
                "OPERATION_TARGET_MISMATCH", "操作与节点目标不匹配", status_code=409
            )
        if operation.cloud_credential_version_id != node.cloud_credential_version_id:
            raise DomainError(
                "CLOUD_CREDENTIAL_VERSION_CONFLICT",
                "操作与节点云凭据版本不匹配",
                status_code=409,
            )
        if str(operation.params.get("region") or "") != node.region:
            raise DomainError("REGION_MISMATCH", "操作区域与节点不匹配", status_code=409)

    @staticmethod
    def _record_step(
        operation: Operation,
        *,
        name: str,
        status: str,
        result: dict | None = None,
        evidence: dict | None = None,
        external_request_id: str = "",
    ) -> None:
        attempt = OperationStep.objects.filter(operation=operation, name=name).count() + 1
        now = timezone.now()
        OperationStep.objects.create(
            operation=operation,
            name=name,
            phase="cloud",
            status=status,
            attempt=attempt,
            result=result or {},
            evidence=evidence or {},
            external_request_id=external_request_id,
            started_at=now,
            finished_at=now,
        )

    @staticmethod
    def _finish(
        claim: Claim,
        *,
        status: str,
        result: dict | None = None,
        error_code: str = "",
        error_details: dict | None = None,
    ) -> Operation:
        with transaction.atomic():
            operation = Operation.objects.select_for_update().get(pk=claim.operation_id)
            assert_current(claim)
            operation.status = status
            operation.result = result or {}
            operation.error_code = error_code
            operation.error_details = error_details or {}
            operation.lease_owner = ""
            operation.lease_expires_at = None
            operation.save(
                update_fields=[
                    "status",
                    "result",
                    "error_code",
                    "error_details",
                    "lease_owner",
                    "lease_expires_at",
                    "updated_at",
                ]
            )
            return operation

    @staticmethod
    def _adopt(node: ManagedNode, operation: Operation, instance) -> None:
        if instance.ref.account.id != node.cloud_account_id or instance.ref.region != node.region:
            raise DomainError(
                "RESOURCE_OWNERSHIP_MISMATCH", "云实例归属不匹配", status_code=409
            )
        expected_tags = {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(operation.idempotency_key),
        }
        if any(instance.tags.get(key) != value for key, value in expected_tags.items()):
            raise DomainError(
                "RESOURCE_OWNERSHIP_MISMATCH", "云实例标签不能证明归属", status_code=409
            )
        with transaction.atomic():
            locked = ManagedNode.objects.select_for_update().get(pk=node.pk)
            locked.external_id = instance.ref.resource_id
            locked.addresses = [
                {
                    "value": address.value,
                    "family": address.family,
                    "kind": address.kind,
                    "resource_id": address.resource_id,
                }
                for address in instance.addresses
            ]
            locked.raw_cloud_state = instance.raw_state
            locked.provisioning_state = "PROVISIONED"
            locked.observed_at = instance.observed_at
            locked.observation_error = ""
            locked.save(
                update_fields=[
                    "external_id",
                    "addresses",
                    "raw_cloud_state",
                    "provisioning_state",
                    "observed_at",
                    "observation_error",
                    "updated_at",
                ]
            )
            NodeResource.objects.get_or_create(
                node=locked,
                kind="instance",
                external_id=instance.ref.resource_id,
                defaults={
                    "ownership_tags": expected_tags,
                    "cost_status": "ACTIVE",
                    "releasable": False,
                },
            )

    def create(self, node_id: UUID, *, operation_id: UUID) -> None:
        node = ManagedNode.objects.select_related(
            "cloud_account", "cloud_credential_version"
        ).get(pk=node_id)
        operation = Operation.objects.get(pk=operation_id)
        self._ensure_scope(node, operation)
        claim = claim_operation(operation_id, worker_id=self.worker_id)
        operation = assert_current(claim)
        authorizer = DatabaseWriteAuthorizer(claim)
        provider = self.provider_for(node, authorizer)
        request = self._request(node, operation)

        matches = provider.find_instance_by_request(request, str(operation.idempotency_key))
        if len(matches) > 1:
            self._finish(
                claim,
                status="NEEDS_RECONCILIATION",
                error_code="MULTIPLE_CLOUD_RESOURCES",
            )
            return
        if len(matches) == 1:
            self._adopt(node, operation, matches[0])
            self._record_step(operation, name="cloud.create", status="RECONCILED")
            self._finish(claim, status="SUCCEEDED", result={"adopted": True})
            return

        permit = self._permit(node, operation, claim, "create", resource_id=None)
        try:
            mutation = provider.create_instance(request, permit=permit)
        except DomainError as exc:
            if exc.code == "CLOUD_WRITE_OUTCOME_UNKNOWN":
                ManagedNode.objects.filter(pk=node.pk).update(
                    provisioning_state="RECONCILIATION",
                    observation_error=exc.code,
                    updated_at=timezone.now(),
                )
                self._record_step(
                    operation,
                    name="cloud.create",
                    status="UNKNOWN",
                    evidence=exc.details,
                )
                self._finish(
                    claim,
                    status="NEEDS_RECONCILIATION",
                    error_code=exc.code,
                    error_details=exc.details,
                )
                return
            self._finish(claim, status="FAILED", error_code=exc.code, error_details=exc.details)
            raise
        self._record_step(
            operation,
            name="cloud.create",
            status=mutation.outcome.upper(),
            external_request_id=mutation.request_id or "",
        )
        if mutation.outcome == "unknown":
            self._finish(
                claim,
                status="NEEDS_RECONCILIATION",
                error_code="CLOUD_WRITE_OUTCOME_UNKNOWN",
            )
            return
        matches = provider.find_instance_by_request(request, str(operation.idempotency_key))
        if len(matches) != 1:
            self._finish(
                claim,
                status="NEEDS_RECONCILIATION",
                error_code="CLOUD_READ_AFTER_WRITE_UNCONFIRMED",
            )
            return
        self._adopt(node, operation, matches[0])
        self._finish(
            claim,
            status="SUCCEEDED",
            result={"resource_id": matches[0].ref.resource_id},
        )

    def reconcile(self, node_id: UUID, *, operation_id: UUID) -> None:
        node = ManagedNode.objects.select_related(
            "cloud_account", "cloud_credential_version"
        ).get(pk=node_id)
        operation = Operation.objects.get(pk=operation_id)
        self._ensure_scope(node, operation)
        claim = claim_operation(operation_id, worker_id=self.worker_id)
        operation = assert_current(claim)
        provider = self.provider_for(node, DatabaseWriteAuthorizer(claim))
        request = self._request(node, operation)
        matches = provider.find_instance_by_request(request, str(operation.idempotency_key))
        if len(matches) != 1:
            self._finish(
                claim,
                status="NEEDS_RECONCILIATION",
                error_code="CLOUD_RESOURCE_NOT_UNAMBIGUOUS",
                error_details={"match_count": len(matches)},
            )
            return
        self._adopt(node, operation, matches[0])
        self._record_step(operation, name="cloud.reconcile", status="SUCCEEDED")
        self._finish(
            claim,
            status="SUCCEEDED",
            result={"resource_id": matches[0].ref.resource_id, "reconciled": True},
        )

    @staticmethod
    def _firewall_safe(snapshot) -> bool:
        for rule in snapshot.rules:
            if rule.protocol in {"all", "udp"}:
                return False
            if rule.port_from is None or rule.port_to is None:
                return False
            if rule.port_from != 22 or rule.port_to != 22:
                return False
        return True

    def quarantine(self, node_id: UUID, *, operation_id: UUID) -> IsolationResult:
        node = ManagedNode.objects.select_related(
            "cloud_account", "cloud_credential_version"
        ).get(pk=node_id)
        operation = Operation.objects.get(pk=operation_id)
        self._ensure_scope(node, operation)
        if not node.external_id:
            raise DomainError("NODE_NOT_PROVISIONED", "节点尚无云实例", status_code=409)
        claim = claim_operation(operation_id, worker_id=self.worker_id)
        operation = assert_current(claim)
        provider = self.provider_for(node, DatabaseWriteAuthorizer(claim))
        resource = ResourceRef(self._account_ref(node), node.region, node.external_id)
        permit = self._permit(
            node, operation, claim, "firewall", resource_id=node.external_id
        )
        ssh_source = str(operation.params.get("ssh_source") or "")
        rules = (
            (
                FirewallRule("tcp", 22, 22, ssh_source, "cidr", 6 if ":" in ssh_source else 4),
            )
            if ssh_source
            else ()
        )
        mutation = provider.configure_firewall(resource, rules, permit=permit)
        snapshot = provider.get_firewall(resource)
        firewall_safe = mutation.outcome != "unknown" and self._firewall_safe(snapshot)
        probe = dict(self.isolation_probe(node) or {})
        confirmed = bool(
            firewall_safe
            and probe.get("fresh_connections_blocked") is True
            and probe.get("existing_sessions_closed") is True
            and probe.get("positive_control") is True
        )
        evidence = {
            "firewall_request_id": mutation.request_id,
            "firewall_read_request_id": snapshot.request_id,
            "firewall_safe": firewall_safe,
            "data_plane": probe,
        }
        ManagedNode.objects.filter(pk=node.pk).update(
            security_state="QUARANTINED" if confirmed else "ISOLATION_UNCONFIRMED",
            updated_at=timezone.now(),
        )
        self._record_step(
            operation,
            name="security.quarantine",
            status="SUCCEEDED" if confirmed else "UNCONFIRMED",
            evidence=evidence,
            external_request_id=mutation.request_id or "",
        )
        self._finish(
            claim,
            status="SUCCEEDED" if confirmed else "PARTIALLY_SUCCEEDED",
            result={"isolation_confirmed": confirmed, "evidence": evidence},
            error_code="" if confirmed else "ISOLATION_UNCONFIRMED",
        )
        return IsolationResult(confirmed, evidence)

    def dispatch(self, kind: str, node_id: UUID, *, operation_id: UUID) -> None:
        if kind == "create":
            return self.create(node_id, operation_id=operation_id)
        if kind == "quarantine":
            self.quarantine(node_id, operation_id=operation_id)
            return None
        if kind == "reconcile":
            return self.reconcile(node_id, operation_id=operation_id)
        if kind not in {"start", "stop", "reboot", "delete", "rotate_ip", "reinstall"}:
            raise DomainError("OPERATION_KIND_UNSUPPORTED", "不支持的节点操作", status_code=400)

        node = ManagedNode.objects.select_related(
            "cloud_account", "cloud_credential_version"
        ).get(pk=node_id)
        operation = Operation.objects.get(pk=operation_id)
        self._ensure_scope(node, operation)
        if (
            kind in {"start", "reboot", "reinstall"}
            and node.security_state in UNSAFE_SECURITY_STATES
        ):
            if operation.params.get("verified_restore") is not True:
                raise DomainError("RESTORE_REQUIRED", "需先完成撤销状态核验", status_code=409)
        if kind == "reinstall":
            raise DomainError(
                "REINSTALL_CONFIRMATION_REQUIRED", "重装必须使用独立破坏性确认流程", status_code=409
            )
        if kind == "rotate_ip":
            raise DomainError(
                "CAPABILITY_UNSUPPORTED", "当前节点不支持安全的原地换 IP", status_code=409
            )
        if not node.external_id:
            raise DomainError("NODE_NOT_PROVISIONED", "节点尚无云实例", status_code=409)

        claim = claim_operation(operation_id, worker_id=self.worker_id)
        operation = assert_current(claim)
        provider = self.provider_for(node, DatabaseWriteAuthorizer(claim))
        resource = ResourceRef(self._account_ref(node), node.region, node.external_id)
        permit = self._permit(node, operation, claim, kind, resource_id=node.external_id)
        method = getattr(provider, f"{kind}_instance")
        try:
            mutation = method(resource, permit=permit)
        except DomainError as exc:
            status = (
                "NEEDS_RECONCILIATION"
                if exc.code == "CLOUD_WRITE_OUTCOME_UNKNOWN"
                else "FAILED"
            )
            self._finish(claim, status=status, error_code=exc.code, error_details=exc.details)
            raise
        status = "NEEDS_RECONCILIATION" if mutation.outcome != "completed" else "SUCCEEDED"
        self._finish(
            claim,
            status=status,
            result={"provider_request_id": mutation.request_id, "outcome": mutation.outcome},
            error_code="CLOUD_READ_AFTER_WRITE_REQUIRED" if status != "SUCCEEDED" else "",
        )
        return None
