from __future__ import annotations

import os
import socket
import time
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.operations.authorization import DatabaseWriteAuthorizer
from apps.operations.claims import Claim, assert_current, claim_operation, renew_claim
from apps.operations.models import Operation, OperationStep
from common.errors import DomainError
from providers.base import (
    AccountRef,
    CreateRequest,
    FirewallRule,
    MutationPermit,
    ResourceRef,
)
from providers.registry import build_read_provider, build_write_provider

from .execution_types import IsolationResult
from .models import ManagedNode, NodeConfigRevision, NodeResource
from .quota import release_quota

UNSAFE_SECURITY_STATES = {
    "REVOKING",
    "REVOCATION_UNCONFIRMED",
    "ISOLATION_UNCONFIRMED",
    "QUARANTINED",
    "MAINTENANCE",
}

PROVIDER_OPERATION_TIMEOUT_SECONDS = 90
PROVIDER_OPERATION_POLL_INTERVAL_SECONDS = 2
INSTANCE_READBACK_TIMEOUT_SECONDS = 60
INSTANCE_READBACK_POLL_INTERVAL_SECONDS = 2
INSTANCE_STABLE_READS = 3
LIFECYCLE_OPERATION_LEASE_SECONDS = 240


def _node_delete_snapshot(node: ManagedNode) -> dict:
    return {
        "external_id": node.external_id,
        "region": node.region,
        "account_id": str(node.cloud_account_id),
        "addresses": list(node.addresses or []),
        "desired_state": node.desired_state,
        "desired_generation": node.desired_generation,
    }


def _default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


class NodeLifecycle:
    def __init__(
        self,
        *,
        provider_factory=None,
        reader_factory=None,
        isolation_probe=None,
        health_probe=None,
        worker_id: str | None = None,
    ):
        self.provider_factory = provider_factory or self._build_provider
        self.reader_factory = reader_factory or (
            (lambda node: provider_factory(node, None))
            if provider_factory is not None
            else self._build_reader
        )
        self.isolation_probe = isolation_probe or (lambda _node: {})
        self.health_probe = health_probe
        self.worker_id = worker_id or _default_worker_id()

    @staticmethod
    def _build_provider(node: ManagedNode, authorizer):
        return build_write_provider(
            node.cloud_account_id,
            node.region,
            authorizer=authorizer,
            credential_version=node.cloud_credential_version.version,
        )

    @staticmethod
    def _build_reader(node: ManagedNode):
        return build_read_provider(
            node.cloud_account_id,
            node.region,
            credential_version=node.cloud_credential_version.version,
        )

    def provider_for(self, node: ManagedNode, authorizer):
        return self.provider_factory(node, authorizer)

    @staticmethod
    def _wait_for_provider_operation(
        provider, operation_id, resource, action, *, renew_claim_callback=None
    ):
        get_status = getattr(provider, "get_operation_status", None)
        if not callable(get_status):
            return "UNCONFIRMED", "CLOUD_OPERATION_STATUS_UNSUPPORTED"
        deadline = time.monotonic() + PROVIDER_OPERATION_TIMEOUT_SECONDS
        last_renewal = time.monotonic()
        while True:
            now = time.monotonic()
            if (
                renew_claim_callback
                and now - last_renewal >= LIFECYCLE_OPERATION_LEASE_SECONDS // 2
            ):
                renew_claim_callback()
                last_renewal = now
            try:
                status = get_status(operation_id, resource, action=action)
            except DomainError as exc:
                return "UNCONFIRMED", exc.code
            except Exception:
                return "UNCONFIRMED", "CLOUD_OPERATION_STATUS_READ_FAILED"
            if status in {"SUCCEEDED", "FAILED"}:
                return status, "" if status == "SUCCEEDED" else "CLOUD_OPERATION_FAILED"
            if status != "IN_PROGRESS":
                return "UNCONFIRMED", "CLOUD_OPERATION_STATE_UNKNOWN"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "TIMED_OUT", "CLOUD_OPERATION_PENDING"
            time.sleep(min(PROVIDER_OPERATION_POLL_INTERVAL_SECONDS, remaining))

    @staticmethod
    def _wait_for_instance_readback(
        provider,
        resource,
        *,
        expected_state,
        previous_ipv4=(),
        require_ipv4_change=False,
        renew_claim_callback=None,
    ):
        deadline = time.monotonic() + INSTANCE_READBACK_TIMEOUT_SECONDS
        last_renewal = time.monotonic()
        previous_snapshot = None
        stable_reads = 0
        latest_state = "UNKNOWN"
        last_error = ""
        while True:
            now = time.monotonic()
            if (
                renew_claim_callback
                and now - last_renewal >= LIFECYCLE_OPERATION_LEASE_SECONDS // 2
            ):
                renew_claim_callback()
                last_renewal = now
            try:
                instance = provider.get_instance(resource)
            except DomainError as exc:
                if exc.code in {"RESOURCE_OWNERSHIP_MISMATCH", "CLOUD_OPERATION_TARGET_MISMATCH"}:
                    return None, exc.code
                instance = None
                last_error = exc.code
            except Exception:
                instance = None
                last_error = "CLOUD_READ_AFTER_WRITE_FAILED"

            if instance is not None:
                last_error = ""
                latest_state = str(instance.state).casefold()
                ipv4 = tuple(
                    sorted(
                        (address.value, address.kind, address.resource_id)
                        for address in instance.addresses
                        if address.family == 4
                    )
                )
                snapshot = (latest_state, str(instance.raw_state), ipv4)
                changed_ipv4 = not require_ipv4_change or any(
                    address[0] not in previous_ipv4 for address in ipv4
                )
                if latest_state == expected_state and ipv4 and changed_ipv4:
                    stable_reads = stable_reads + 1 if snapshot == previous_snapshot else 1
                    if stable_reads >= INSTANCE_STABLE_READS:
                        return instance, ""
                else:
                    stable_reads = 0
                previous_snapshot = snapshot
            else:
                stable_reads = 0
                previous_snapshot = None

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if latest_state != expected_state:
                    return None, last_error or "CLOUD_STATE_UNEXPECTED"
                if instance is None:
                    return None, last_error or "CLOUD_READ_AFTER_WRITE_FAILED"
                if not ipv4:
                    return None, "CLOUD_IPV4_READBACK_UNAVAILABLE"
                if require_ipv4_change and not changed_ipv4:
                    return None, "CLOUD_ADDRESS_PROPAGATION_PENDING"
                return None, last_error or "CLOUD_READ_AFTER_WRITE_UNCONFIRMED"
            time.sleep(min(INSTANCE_READBACK_POLL_INTERVAL_SECONDS, remaining))

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
        started_at=None,
        result: dict | None = None,
        evidence: dict | None = None,
        external_request_id: str = "",
        finished: bool = True,
    ) -> OperationStep:
        attempt = OperationStep.objects.filter(operation=operation, name=name).count() + 1
        now = timezone.now()
        return OperationStep.objects.create(
            operation=operation,
            name=name,
            phase="cloud",
            status=status,
            attempt=attempt,
            result=result or {},
            evidence=evidence or {},
            external_request_id=external_request_id,
            started_at=started_at or now,
            finished_at=now if finished else None,
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
            automation = operation.params.get("automation")
            if (
                status == "SUCCEEDED"
                and operation.kind == "node.reboot"
                and isinstance(automation, dict)
                and automation.get("kind") == "daily_restart"
            ):
                from apps.identity.models import NodeAutomationSetting

                setting = NodeAutomationSetting.objects.select_for_update().filter(
                    singleton_key=1
                ).first()
                if setting is not None:
                    setting.daily_restart_last_success_node_id = operation.target_id
                    setting.save(
                        update_fields=["daily_restart_last_success_node_id", "updated_at"]
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

    @staticmethod
    def _mark_observation_error(node: ManagedNode, code: str) -> None:
        ManagedNode.objects.filter(
            pk=node.pk,
            cloud_account_id=node.cloud_account_id,
            region=node.region,
            external_id=node.external_id,
        ).update(observation_error=code, updated_at=timezone.now())

    @staticmethod
    def _record_instance_observation(
        node: ManagedNode,
        resource: ResourceRef,
        instance,
        *,
        refresh_subscriptions: bool = False,
        defer_subscription_refresh: bool = False,
    ) -> dict:
        if instance.ref != resource:
            raise DomainError(
                "RESOURCE_OWNERSHIP_MISMATCH", "云读回资源与操作目标不匹配", status_code=409
            )
        expected_tags = {
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        }
        if any(instance.tags.get(key) != value for key, value in expected_tags.items()):
            raise DomainError(
                "RESOURCE_OWNERSHIP_MISMATCH", "云实例标签不能证明归属", status_code=409
            )

        addresses = [
            {
                "value": address.value,
                "family": address.family,
                "kind": address.kind,
                "resource_id": address.resource_id,
            }
            for address in instance.addresses
        ]
        with transaction.atomic():
            locked = ManagedNode.objects.select_for_update().get(pk=node.pk)
            if (
                locked.cloud_account_id != resource.account.id
                or locked.region != resource.region
                or locked.external_id != resource.resource_id
                or locked.desired_state == "DELETED"
            ):
                raise DomainError(
                    "NODE_TARGET_CHANGED", "节点目标在云读回期间发生变化", status_code=409
                )
            addresses_changed = locked.addresses != addresses
            locked.addresses = addresses
            locked.raw_cloud_state = instance.raw_state
            locked.observed_at = instance.observed_at
            locked.observation_error = ""
            locked.save(
                update_fields=[
                    "addresses",
                    "raw_cloud_state",
                    "observed_at",
                    "observation_error",
                    "updated_at",
                ]
            )

            publication = {"published": 0, "failed": 0}
            if (addresses_changed or refresh_subscriptions) and not defer_subscription_refresh:
                from apps.subscriptions.publishing import Publisher

                publication = Publisher.refresh_node_address(locked.pk)
        return {
            "addresses_changed": addresses_changed,
            "published": publication["published"],
            "publication_failures": publication["failed"],
        }

    def _probe_reboot_health(self, node: ManagedNode) -> tuple[str, str, dict, int]:
        from .probes import run_node_health_probe

        return run_node_health_probe(node, self.health_probe)

    @staticmethod
    def _record_reboot_health(
        node: ManagedNode,
        resource: ResourceRef,
        *,
        generation: int,
        health_state: str,
        probe_status: str,
        probe_evidence: dict[str, bool | None],
    ) -> str:
        from .probes import record_node_health_probe

        return record_node_health_probe(
            node,
            external_id=resource.resource_id,
            generation=generation,
            health_state=health_state,
            probe_status=probe_status,
            probe_evidence=probe_evidence,
        )

    @staticmethod
    def _refresh_subscriptions_after_reboot(node_id: UUID) -> dict[str, int]:
        from apps.subscriptions.publishing import Publisher

        try:
            return Publisher.refresh_node_address(node_id)
        except Exception:
            return {"published": 0, "failed": 1}

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

    def refresh(self, node_id: UUID, *, operation_id: UUID) -> None:
        node = ManagedNode.objects.select_related(
            "cloud_account", "cloud_credential_version"
        ).get(pk=node_id)
        operation = Operation.objects.get(pk=operation_id)
        self._ensure_scope(node, operation)
        claim = claim_operation(operation_id, worker_id=self.worker_id)
        operation = assert_current(claim)
        if not node.external_id or node.desired_state == "DELETED":
            self._finish(claim, status="FAILED", error_code="NODE_NOT_PROVISIONED")
            return

        resource = ResourceRef(
            self._account_ref(node), node.region, node.external_id
        )
        try:
            instance = self.reader_factory(node).get_instance(resource)
        except DomainError as exc:
            if exc.code == "RESOURCE_NOT_FOUND":
                with transaction.atomic():
                    locked = ManagedNode.objects.select_for_update().get(pk=node.pk)
                    if (
                        locked.cloud_account_id != resource.account.id
                        or locked.region != resource.region
                        or locked.external_id != resource.resource_id
                        or locked.desired_state == "DELETED"
                    ):
                        self._finish(
                            claim,
                            status="FAILED",
                            error_code="NODE_TARGET_CHANGED",
                        )
                        return
                    locked.raw_cloud_state = "NOT_FOUND"
                    locked.observation_error = "RESOURCE_NOT_FOUND"
                    locked.observed_at = timezone.now()
                    locked.save(
                        update_fields=[
                            "raw_cloud_state",
                            "observation_error",
                            "observed_at",
                            "updated_at",
                        ]
                    )
                self._record_step(
                    operation,
                    name="cloud.refresh",
                    status="CONFIRMED_ABSENT",
                    evidence={"error_code": "RESOURCE_NOT_FOUND"},
                )
                self._finish(
                    claim,
                    status="SUCCEEDED",
                    result={"cloud_status": "NOT_FOUND"},
                )
                return
            self._mark_observation_error(node, exc.code)
            self._record_step(
                operation,
                name="cloud.refresh",
                status="FAILED",
                evidence={"error_code": exc.code},
            )
            self._finish(claim, status="FAILED", error_code=exc.code)
            return
        except Exception:
            self._mark_observation_error(node, "CLOUD_STATUS_READ_FAILED")
            self._record_step(
                operation,
                name="cloud.refresh",
                status="FAILED",
                evidence={"error_code": "CLOUD_STATUS_READ_FAILED"},
            )
            self._finish(
                claim, status="FAILED", error_code="CLOUD_STATUS_READ_FAILED"
            )
            return

        try:
            observed = self._record_instance_observation(node, resource, instance)
        except DomainError as exc:
            self._mark_observation_error(node, exc.code)
            self._record_step(
                operation,
                name="cloud.refresh",
                status="FAILED",
                evidence={"error_code": exc.code},
            )
            self._finish(claim, status="FAILED", error_code=exc.code)
            return
        self._record_step(
            operation,
            name="cloud.refresh",
            status="OBSERVED",
            result={"addresses_changed": observed["addresses_changed"]},
        )
        self._finish(
            claim,
            status="SUCCEEDED",
            result={
                "cloud_status": "PRESENT",
                "addresses_changed": observed["addresses_changed"],
            },
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

    def _delete_instance(
        self,
        node: ManagedNode,
        operation: Operation,
        claim: Claim,
        provider,
        resource: ResourceRef,
        permit: MutationPermit,
    ) -> None:
        preview = operation.preview
        if (
            preview is None
            or preview.kind != "node.delete"
            or preview.target_id != node.pk
            or preview.consumed_at is None
            or operation.params.get("confirmation") != preview.required_phrase
        ):
            self._record_step(
                operation,
                name="cloud.delete.preflight",
                status="REJECTED",
                evidence={"reason": "PREVIEW_REQUIRED"},
            )
            self._finish(claim, status="FAILED", error_code="PREVIEW_REQUIRED")
            return

        current_snapshot = _node_delete_snapshot(node)
        if (
            operation.params.get("account_id") != str(node.cloud_account_id)
            or preview.snapshot != current_snapshot
        ):
            self._record_step(
                operation,
                name="cloud.delete.preflight",
                status="STALE",
                evidence={"reason": "PREVIEW_STALE"},
            )
            self._finish(claim, status="FAILED", error_code="PREVIEW_STALE")
            return

        automation = operation.params.get("automation")
        if automation is not None:
            policy_version = (
                automation.get("policy_version") if isinstance(automation, dict) else None
            )
            if (
                not isinstance(automation, dict)
                or automation.get("kind") != "pool_sync"
                or isinstance(policy_version, bool)
                or not isinstance(policy_version, int)
                or policy_version < 1
            ):
                error_code = "AUTOMATED_DELETE_POLICY_INVALID"
            else:
                try:
                    from .automation import validate_automated_delete

                    validate_automated_delete(operation, node, policy_version)
                except DomainError as exc:
                    error_code = exc.code
                except Exception:
                    error_code = "AUTOMATED_DELETE_VALIDATION_FAILED"
                else:
                    error_code = ""
            if error_code:
                self._record_step(
                    operation,
                    name="cloud.delete.automation_preflight",
                    status="REJECTED",
                    evidence={"error_code": error_code},
                )
                self._finish(claim, status="FAILED", error_code=error_code)
                return

        mutation = None
        mutation_error = None
        try:
            mutation = provider.delete_instance(resource, permit=permit)
        except DomainError as exc:
            mutation_error = exc
        except Exception:
            mutation_error = DomainError(
                "CLOUD_WRITE_OUTCOME_UNKNOWN", "云删除写入结果未知，需要对账"
            )

        self._record_step(
            operation,
            name="cloud.delete",
            status=(mutation.outcome.upper() if mutation else "UNKNOWN"),
            external_request_id=mutation.request_id or "" if mutation else "",
            evidence={"error_code": mutation_error.code} if mutation_error else {},
        )

        observed = None
        absence_confirmed = False
        read_error_code = ""
        try:
            observed = provider.get_instance(resource)
        except DomainError as exc:
            if exc.code == "RESOURCE_NOT_FOUND":
                absence_confirmed = True
            else:
                read_error_code = exc.code
        except Exception:
            read_error_code = "CLOUD_READ_AFTER_WRITE_FAILED"

        if observed is None and not absence_confirmed and not read_error_code:
            read_error_code = "CLOUD_READ_AFTER_WRITE_UNCONFIRMED"

        if observed is not None and observed.ref != resource:
            read_error_code = "CLOUD_DELETE_TARGET_MISMATCH"

        if read_error_code:
            self._record_step(
                operation,
                name="cloud.delete.read_after_write",
                status="UNCONFIRMED",
                evidence={"error_code": read_error_code},
            )
            self._finish(
                claim,
                status="NEEDS_RECONCILIATION",
                error_code="CLOUD_DELETE_READ_AFTER_WRITE_UNCONFIRMED",
                error_details={"read_error_code": read_error_code},
            )
            return

        if observed is not None:
            self._record_step(
                operation,
                name="cloud.delete.read_after_write",
                status="RESOURCE_PRESENT",
                evidence={"resource_id": resource.resource_id},
            )
            if mutation_error and mutation_error.code != "CLOUD_WRITE_OUTCOME_UNKNOWN":
                self._finish(
                    claim,
                    status="FAILED",
                    error_code=mutation_error.code,
                    error_details=mutation_error.details,
                )
                raise mutation_error
            self._finish(
                claim,
                status="NEEDS_RECONCILIATION",
                error_code="CLOUD_DELETE_READ_AFTER_WRITE_UNCONFIRMED",
                error_details={"resource_present": True},
            )
            return

        with transaction.atomic():
            locked_node = ManagedNode.objects.select_for_update().get(pk=node.pk)
            if _node_delete_snapshot(locked_node) != preview.snapshot:
                self._record_step(
                    operation,
                    name="cloud.delete.read_after_write",
                    status="DATABASE_TARGET_CHANGED",
                    evidence={"resource_absent": True},
                )
                self._finish(
                    claim,
                    status="NEEDS_RECONCILIATION",
                    error_code="PREVIEW_STALE",
                )
                return
            from apps.subscriptions.publishing import Publisher

            publication_batch = Publisher.invalidate_node(locked_node.pk)
            release_quota(locked_node.pk, cloud_absence_confirmed=True)

        self._record_step(
            operation,
            name="subscriptions.invalidate_deleted_node",
            status=publication_batch.status,
            evidence={
                "publication_batch_id": str(publication_batch.pk),
                "affected_subscriptions": len(publication_batch.subscription_ids),
                "published": publication_batch.result.get("published", 0),
                "failed": len(publication_batch.result.get("failures", [])),
            },
        )
        self._record_step(
            operation,
            name="cloud.delete.read_after_write",
            status="CONFIRMED_ABSENT",
            evidence={"resource_id": resource.resource_id},
        )
        publication_failures = len(publication_batch.result.get("failures", []))
        self._finish(
            claim,
            status="PARTIALLY_SUCCEEDED" if publication_failures else "SUCCEEDED",
            result={
                "resource_id": resource.resource_id,
                "cloud_absence_confirmed": True,
                "quota_released": True,
                "publication_batch_id": str(publication_batch.pk),
                "publication_batch_status": publication_batch.status,
                "subscriptions_published": publication_batch.result.get("published", 0),
                "subscription_publication_failures": publication_failures,
                "provider_request_id": mutation.request_id if mutation else None,
            },
        )

    def dispatch(self, kind: str, node_id: UUID, *, operation_id: UUID) -> None:
        if kind == "create":
            return self.create(node_id, operation_id=operation_id)
        if kind == "refresh":
            return self.refresh(node_id, operation_id=operation_id)
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
        if kind in {"start", "reboot", "reinstall"}:
            from apps.subscriptions.security_barrier import (
                PublishingBlocked,
                SecurityBarrier,
            )

            try:
                SecurityBarrier.assert_open(purpose="reopen_node")
            except PublishingBlocked as exc:
                raise DomainError(
                    "RESTORE_REQUIRED", "需先完成恢复安全核验", status_code=409
                ) from exc
            if node.security_state in UNSAFE_SECURITY_STATES:
                raise DomainError(
                    "RESTORE_REQUIRED", "需先完成撤销状态核验", status_code=409
                )
        if kind == "reinstall":
            raise DomainError(
                "REINSTALL_CONFIRMATION_REQUIRED", "重装必须使用独立破坏性确认流程", status_code=409
            )
        if kind == "rotate_ip":
            raise DomainError(
                "CAPABILITY_UNSUPPORTED", "当前节点不支持安全的原地换 IP", status_code=409
            )
        if not node.external_id or node.desired_state == "DELETED":
            claim = claim_operation(operation_id, worker_id=self.worker_id)
            return self._finish(
                claim,
                status="FAILED",
                error_code="NODE_NOT_PROVISIONED",
                error_details={"resource_unavailable": True},
            )

        tracks_provider_operation = (
            kind in {"start", "reboot"}
            and node.cloud_account.provider == "aws_lightsail"
        )
        claim = claim_operation(
            operation_id,
            worker_id=self.worker_id,
            lease_seconds=LIFECYCLE_OPERATION_LEASE_SECONDS
            if tracks_provider_operation
            else 60,
        )
        operation = assert_current(claim)
        automation = operation.params.get("automation")
        if kind == "reboot" and automation is not None:
            policy_version = (
                automation.get("policy_version") if isinstance(automation, dict) else None
            )
            if (
                not isinstance(automation, dict)
                or automation.get("kind") != "daily_restart"
                or isinstance(policy_version, bool)
                or not isinstance(policy_version, int)
                or policy_version < 1
                or not isinstance(automation.get("local_date"), str)
                or not automation.get("local_date")
            ):
                error_code = "AUTOMATED_RESTART_POLICY_INVALID"
            else:
                try:
                    from .automation import validate_automated_restart

                    validate_automated_restart(operation, node, policy_version)
                except DomainError as exc:
                    error_code = exc.code
                except Exception:
                    error_code = "AUTOMATED_RESTART_VALIDATION_FAILED"
                else:
                    error_code = ""
            if error_code:
                self._record_step(
                    operation,
                    name="cloud.reboot.automation_preflight",
                    status="REJECTED",
                    evidence={"error_code": error_code},
                )
                self._finish(claim, status="FAILED", error_code=error_code)
                return None
        if kind == "reboot":
            with transaction.atomic():
                locked_node = ManagedNode.objects.select_for_update().get(pk=node.pk)
                if (
                    locked_node.external_id == node.external_id
                    and locked_node.desired_state == "PRESENT"
                ):
                    locked_node.health_state = "UNKNOWN"
                    locked_node.save(update_fields=["health_state", "updated_at"])
                    NodeConfigRevision.objects.filter(
                        node=locked_node, generation=locked_node.applied_generation
                    ).update(probe_result={})
        provider = self.provider_for(node, DatabaseWriteAuthorizer(claim))
        resource = ResourceRef(self._account_ref(node), node.region, node.external_id)
        permit = self._permit(node, operation, claim, kind, resource_id=node.external_id)
        if kind == "delete":
            self._delete_instance(node, operation, claim, provider, resource, permit)
            return None
        method = getattr(provider, f"{kind}_instance")
        previous_write_step = (
            operation.steps.filter(name=f"cloud.{kind}").order_by("-attempt").first()
        )
        previous_readback_step = (
            operation.steps.filter(name=f"cloud.{kind}.read_after_write")
            .order_by("-attempt")
            .first()
        )
        previous_evidence = previous_readback_step.evidence if previous_readback_step else {}
        retrying_provider_action = tracks_provider_operation and previous_write_step is not None
        force_subscription_refresh = bool(
            previous_evidence.get("subscription_publication_failures", 0)
        )
        mutation = None
        write_error = None
        current_write_step = previous_write_step
        if tracks_provider_operation and not retrying_provider_action:
            list_operation_ids = getattr(provider, "list_operation_ids", None)
            if not callable(list_operation_ids):
                self._finish(
                    claim,
                    status="FAILED",
                    error_code="CLOUD_OPERATION_SNAPSHOT_UNSUPPORTED",
                )
                return None
            try:
                operation_ids_before_write = list(list_operation_ids(resource, action=kind))
            except DomainError as exc:
                self._record_step(
                    operation,
                    name=f"cloud.{kind}",
                    status="SNAPSHOT_FAILED",
                    evidence={"error_code": exc.code},
                )
                self._finish(claim, status="FAILED", error_code=exc.code)
                return None
            except Exception:
                self._record_step(
                    operation,
                    name=f"cloud.{kind}",
                    status="SNAPSHOT_FAILED",
                    evidence={"error_code": "CLOUD_OPERATION_SNAPSHOT_FAILED"},
                )
                self._finish(
                    claim,
                    status="FAILED",
                    error_code="CLOUD_OPERATION_SNAPSHOT_FAILED",
                )
                return None

            current_write_step = self._record_step(
                operation,
                name=f"cloud.{kind}",
                status="WRITE_INTENT",
                evidence={"provider_operation_ids_before_write": operation_ids_before_write},
                finished=False,
            )
            try:
                mutation = method(resource, permit=permit)
            except DomainError as exc:
                write_error = exc
            except Exception:
                write_error = DomainError(
                    "CLOUD_WRITE_OUTCOME_UNKNOWN", "云操作结果未知，需要对账", status_code=502
                )

            write_evidence = dict(current_write_step.evidence)
            if write_error:
                write_evidence["error_code"] = write_error.code
            if mutation and mutation.operation_id:
                write_evidence["provider_operation_id"] = mutation.operation_id
            OperationStep.objects.filter(pk=current_write_step.pk).update(
                status=mutation.outcome.upper() if mutation else "UNKNOWN",
                external_request_id=mutation.request_id or "" if mutation else "",
                evidence=write_evidence,
                finished_at=timezone.now(),
            )
            current_write_step.refresh_from_db()
        elif not tracks_provider_operation:
            write_started_at = timezone.now()
            try:
                mutation = method(resource, permit=permit)
            except DomainError as exc:
                write_error = exc
            except Exception:
                write_error = DomainError(
                    "CLOUD_WRITE_OUTCOME_UNKNOWN", "云操作结果未知，需要对账", status_code=502
                )
            current_write_step = self._record_step(
                operation,
                name=f"cloud.{kind}",
                status=mutation.outcome.upper() if mutation else "UNKNOWN",
                started_at=write_started_at,
                external_request_id=mutation.request_id or "" if mutation else "",
                evidence={"error_code": write_error.code} if write_error else {},
            )

        provider_operation_id = (
            mutation.operation_id
            if mutation and mutation.operation_id
            else (
                current_write_step.evidence.get("provider_operation_id")
                if current_write_step
                else None
            )
        )
        provider_operation_status = "NOT_REQUIRED"
        provider_operation_error = ""
        unattributed_operation_candidate_found = False
        if tracks_provider_operation:
            if not provider_operation_id:
                list_operation_ids = getattr(provider, "list_operation_ids", None)
                before_operation_ids = (
                    current_write_step.evidence.get("provider_operation_ids_before_write")
                    if current_write_step
                    else None
                )
                if (
                    callable(list_operation_ids)
                    and current_write_step
                    and isinstance(before_operation_ids, list)
                ):
                    try:
                        current_operation_ids = set(
                            list_operation_ids(resource, action=kind)
                        )
                        candidate_count = len(
                            current_operation_ids - set(before_operation_ids)
                        )
                        unattributed_operation_candidate_found = candidate_count > 0
                        if candidate_count > 1:
                            provider_operation_error = "CLOUD_OPERATION_LOOKUP_AMBIGUOUS"
                        elif candidate_count == 1:
                            provider_operation_error = "CLOUD_OPERATION_ID_UNOWNED"
                    except DomainError as exc:
                        provider_operation_error = exc.code
                    except Exception:
                        provider_operation_error = "CLOUD_OPERATION_LOOKUP_FAILED"
                elif current_write_step:
                    provider_operation_error = "CLOUD_OPERATION_SNAPSHOT_MISSING"
            if provider_operation_id:
                provider_operation_status, provider_operation_error = (
                    self._wait_for_provider_operation(
                        provider,
                        provider_operation_id,
                        resource,
                        kind,
                        renew_claim_callback=lambda: renew_claim(
                            claim, lease_seconds=LIFECYCLE_OPERATION_LEASE_SECONDS
                        ),
                    )
                )
            else:
                provider_operation_status = "UNCONFIRMED"
                if not provider_operation_error:
                    provider_operation_error = "CLOUD_OPERATION_ID_MISSING"

            if provider_operation_status != "SUCCEEDED":
                error_code = (
                    write_error.code
                    if write_error and write_error.code != "CLOUD_WRITE_OUTCOME_UNKNOWN"
                    else provider_operation_error or "CLOUD_OPERATION_PENDING"
                )
                self._mark_observation_error(node, error_code)
                self._record_step(
                    operation,
                    name=f"cloud.{kind}.read_after_write",
                    status=(
                        "FAILED"
                        if provider_operation_status == "FAILED"
                        else "OPERATION_UNCONFIRMED"
                    ),
                    evidence={
                        "error_code": error_code,
                        "provider_operation_status": provider_operation_status,
                        **(
                            {"provider_operation_error": provider_operation_error}
                            if provider_operation_error
                            else {}
                        ),
                        **(
                            {"provider_operation_id": provider_operation_id}
                            if provider_operation_id
                            else {}
                        ),
                        **(
                            {"unattributed_operation_candidate_found": True}
                            if unattributed_operation_candidate_found
                            else {}
                        ),
                    },
                )
                self._finish(
                    claim,
                    status=(
                        "FAILED"
                        if provider_operation_status == "FAILED"
                        or (write_error and write_error.code != "CLOUD_WRITE_OUTCOME_UNKNOWN")
                        else "NEEDS_RECONCILIATION"
                    ),
                    error_code=error_code,
                    error_details=write_error.details if write_error else {},
                )
                return None

        instance = None
        read_error_code = ""
        expected_state = {"start": "running", "reboot": "running", "stop": "stopped"}.get(
            kind
        )
        if tracks_provider_operation:
            previous_ipv4 = tuple(
                sorted(
                    str(address.get("value"))
                    for address in node.addresses or []
                    if isinstance(address, dict)
                    and address.get("value")
                    and address.get("kind") == "dynamic"
                    and address.get("family", 4) == 4
                )
            )
            require_ipv4_change = (
                kind == "start"
                and str(node.raw_cloud_state).casefold() == "stopped"
                and bool(previous_ipv4)
            )
            instance, read_error_code = self._wait_for_instance_readback(
                provider,
                resource,
                expected_state=expected_state,
                previous_ipv4=previous_ipv4,
                require_ipv4_change=require_ipv4_change,
                renew_claim_callback=lambda: renew_claim(
                    claim, lease_seconds=LIFECYCLE_OPERATION_LEASE_SECONDS
                ),
            )
        else:
            try:
                instance = provider.get_instance(resource)
            except DomainError as exc:
                read_error_code = exc.code
            except Exception:
                read_error_code = "CLOUD_READ_AFTER_WRITE_FAILED"
        if instance is None and not read_error_code:
            read_error_code = "CLOUD_READ_AFTER_WRITE_EMPTY"

        if read_error_code:
            error_code = (
                read_error_code
                if read_error_code in {
                    "CLOUD_ADDRESS_PROPAGATION_PENDING",
                    "CLOUD_STATE_UNEXPECTED",
                    "CLOUD_IPV4_READBACK_UNAVAILABLE",
                }
                else "CLOUD_READ_AFTER_WRITE_UNCONFIRMED"
            )
            self._mark_observation_error(node, error_code)
            self._record_step(
                operation,
                name=f"cloud.{kind}.read_after_write",
                status=(
                    "OPERATION_UNCONFIRMED"
                    if tracks_provider_operation
                    else "UNCONFIRMED"
                ),
                evidence={
                    "error_code": error_code,
                    "provider_operation_status": provider_operation_status,
                    **(
                        {"provider_operation_id": provider_operation_id}
                        if provider_operation_id
                        else {}
                    ),
                    **(
                        {"provider_operation_error": provider_operation_error}
                        if provider_operation_error
                        else {}
                    ),
                },
            )
            self._finish(
                claim,
                status="NEEDS_RECONCILIATION",
                error_code=error_code,
                error_details={"provider_read_error": read_error_code},
            )
            return None

        if tracks_provider_operation:
            claim = renew_claim(claim, lease_seconds=LIFECYCLE_OPERATION_LEASE_SECONDS)
        try:
            observation = self._record_instance_observation(
                node,
                resource,
                instance,
                refresh_subscriptions=force_subscription_refresh,
                defer_subscription_refresh=kind == "reboot",
            )
        except DomainError as exc:
            error_code = (
                "CLOUD_READ_AFTER_WRITE_TARGET_MISMATCH"
                if exc.code in {"RESOURCE_OWNERSHIP_MISMATCH", "NODE_TARGET_CHANGED"}
                else "CLOUD_READ_AFTER_WRITE_UNCONFIRMED"
            )
            self._mark_observation_error(node, exc.code)
            self._record_step(
                operation,
                name=f"cloud.{kind}.read_after_write",
                status="TARGET_MISMATCH",
                evidence={
                    "error_code": error_code,
                    "provider_operation_status": provider_operation_status,
                },
            )
            self._finish(
                claim,
                status="NEEDS_RECONCILIATION",
                error_code=error_code,
                error_details={"observation_error": exc.code},
            )
            return None
        except Exception:
            error_code = "CLOUD_OBSERVATION_WRITE_FAILED"
            self._mark_observation_error(node, error_code)
            self._record_step(
                operation,
                name=f"cloud.{kind}.read_after_write",
                status="UNCONFIRMED",
                evidence={
                    "error_code": error_code,
                    "provider_operation_status": provider_operation_status,
                },
            )
            self._finish(
                claim,
                status="NEEDS_RECONCILIATION",
                error_code=error_code,
            )
            return None

        expected_state = {"start": "running", "reboot": "running", "stop": "stopped"}.get(
            kind
        )
        state_matches = str(instance.state).casefold() == expected_state
        health_probe_status = "NOT_REQUIRED"
        health_state = ""
        health_probe_evidence = {}
        health_error_code = ""
        node_reconciliation = {"scheduled": 0, "operation_ids": []}
        publication = {
            "published": observation["published"],
            "failed": observation["publication_failures"],
        }
        if kind == "reboot":
            if state_matches:
                (
                    health_probe_status,
                    health_state,
                    health_probe_evidence,
                    health_generation,
                ) = self._probe_reboot_health(node)
            else:
                health_probe_status = "SKIPPED_CLOUD_STATE_UNCONFIRMED"
                health_state = "UNKNOWN"
                health_generation = node.applied_generation
                health_probe_evidence = {
                    "accepted": None,
                    "positive_control": None,
                    "fresh_connection": None,
                }
            health_error_code = self._record_reboot_health(
                node,
                resource,
                generation=health_generation,
                health_state=health_state,
                probe_status=(
                    "UNAVAILABLE"
                    if health_probe_status in {"UNAVAILABLE", "SKIPPED_CLOUD_STATE_UNCONFIRMED"}
                    else health_probe_status
                ),
                probe_evidence=health_probe_evidence,
            )
            if not state_matches:
                health_error_code = "CLOUD_STATE_UNEXPECTED"

            if not health_error_code and health_state == "HEALTHY":
                try:
                    from apps.subscriptions.access import (
                        reconcile_node_for_active_subscriptions,
                    )

                    node_reconciliation = reconcile_node_for_active_subscriptions(node.pk)
                except Exception:
                    health_error_code = "NODE_SUBSCRIPTION_RECONCILIATION_FAILED"

            if (
                observation["addresses_changed"]
                or force_subscription_refresh
                or health_state != "HEALTHY"
            ):
                publication = self._refresh_subscriptions_after_reboot(node.pk)

        operation_confirmed = (
            not tracks_provider_operation or provider_operation_status == "SUCCEEDED"
        )
        self._record_step(
            operation,
            name=f"cloud.{kind}.read_after_write",
            status=(
                "CONFIRMED"
                if state_matches and operation_confirmed
                else "OPERATION_UNCONFIRMED"
                if not operation_confirmed
                else "STATE_UNCONFIRMED"
            ),
            evidence={
                "state": str(instance.state),
                "provider_operation_status": provider_operation_status,
                **(
                    {"provider_operation_error": provider_operation_error}
                    if provider_operation_error
                    else {}
                ),
                **(
                    {"provider_operation_id": provider_operation_id}
                    if provider_operation_id
                    else {}
                ),
                **(
                    {"address_stabilized": True}
                    if tracks_provider_operation
                    else {}
                ),
                "addresses_changed": observation["addresses_changed"],
                "subscriptions_published": publication["published"],
                "subscription_publication_failures": publication["failed"],
                **(
                    {
                        "health_probe_status": health_probe_status,
                        "health_state": health_state,
                        "health_probe": health_probe_evidence,
                        "node_reconciliation": node_reconciliation,
                    }
                    if kind == "reboot"
                    else {}
                ),
            },
        )

        if write_error and write_error.code != "CLOUD_WRITE_OUTCOME_UNKNOWN":
            status = (
                "FAILED"
            )
            error_code = write_error.code
        elif tracks_provider_operation and provider_operation_status != "SUCCEEDED":
            status = "NEEDS_RECONCILIATION"
            error_code = provider_operation_error or "CLOUD_OPERATION_PENDING"
        elif retrying_provider_action or (
            tracks_provider_operation
            and write_error
            and write_error.code == "CLOUD_WRITE_OUTCOME_UNKNOWN"
        ):
            status = "SUCCEEDED" if state_matches else "NEEDS_RECONCILIATION"
            error_code = "" if state_matches else "CLOUD_STATE_UNEXPECTED"
            if publication["failed"]:
                status = "NEEDS_RECONCILIATION"
                error_code = "SUBSCRIPTION_ADDRESS_REFRESH_PARTIAL"
        elif write_error:
            status = "NEEDS_RECONCILIATION"
            error_code = write_error.code
        elif mutation is None or mutation.outcome == "unknown":
            status = "NEEDS_RECONCILIATION"
            error_code = "CLOUD_WRITE_OUTCOME_UNKNOWN"
        elif not state_matches:
            status = "NEEDS_RECONCILIATION"
            error_code = "CLOUD_STATE_UNEXPECTED"
        elif publication["failed"]:
            status = "NEEDS_RECONCILIATION"
            error_code = "SUBSCRIPTION_ADDRESS_REFRESH_PARTIAL"
        else:
            status = "SUCCEEDED"
            error_code = ""

        if kind == "reboot" and health_error_code and status != "FAILED":
            status = "NEEDS_RECONCILIATION"
            error_code = health_error_code

        self._finish(
            claim,
            status=status,
            result={
                "provider_request_id": (
                    mutation.request_id
                    if mutation
                    else previous_write_step.external_request_id
                    if retrying_provider_action
                    else None
                ),
                "outcome": (
                    mutation.outcome
                    if mutation
                    else "reconciled"
                    if retrying_provider_action
                    or (write_error and write_error.code == "CLOUD_WRITE_OUTCOME_UNKNOWN")
                    else "unknown"
                ),
                "reconciled": retrying_provider_action
                or (write_error and write_error.code == "CLOUD_WRITE_OUTCOME_UNKNOWN"),
                "provider_operation_status": provider_operation_status,
                "provider_operation_id": provider_operation_id,
                "observed_state": str(instance.state),
                "addresses_changed": observation["addresses_changed"],
                "subscriptions_published": publication["published"],
                "subscription_publication_failures": publication["failed"],
                **(
                    {
                        "health_probe_status": health_probe_status,
                        "health_state": health_state,
                        "health_probe": health_probe_evidence,
                        "node_reconciliation": node_reconciliation,
                    }
                    if kind == "reboot"
                    else {}
                ),
            },
            error_code=error_code,
            error_details=write_error.details if write_error else {},
        )
        return None
