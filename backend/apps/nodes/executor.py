from __future__ import annotations

import hashlib
import json
from uuid import UUID

from django.conf import settings
from django.db import transaction

from apps.operations.models import Operation
from common.errors import DomainError

from .execution_types import ApplyResult, ProbeResult
from .models import ManagedNode, NodeConfigRevision


def _config_hash(config: dict) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


class NodeExecutor:
    def __init__(self, *, transport_factory, probe_runner=None, session_runner=None):
        self.transport_factory = transport_factory
        self.probe_runner = probe_runner
        self.session_runner = session_runner

    @staticmethod
    def _scope(node: ManagedNode, operation_id: UUID) -> Operation:
        try:
            operation = Operation.objects.get(pk=operation_id)
        except Operation.DoesNotExist as exc:
            raise DomainError("OPERATION_NOT_FOUND", "操作不存在", status_code=404) from exc
        if operation.target_id != node.pk or operation.target_type != "node":
            raise DomainError(
                "OPERATION_TARGET_MISMATCH", "操作与节点目标不匹配", status_code=409
            )
        return operation

    def apply_config(
        self,
        node_id: UUID,
        *,
        generation: int,
        config: dict,
        operation_id: UUID,
        allow_security_rollback: bool = False,
    ) -> ApplyResult:
        with transaction.atomic():
            node = ManagedNode.objects.select_for_update().get(pk=node_id)
            self._scope(node, operation_id)
            if generation <= node.applied_generation or generation <= node.desired_generation:
                raise DomainError(
                    "STALE_CONFIG_GENERATION", "配置 generation 不是严格递增", status_code=409
                )
            previous_generation = node.applied_generation
            node.desired_generation = generation
            node.save(update_fields=["desired_generation", "updated_at"])

        transport = self.transport_factory(node)
        if transport is None:
            raise DomainError("NODE_TRANSPORT_UNAVAILABLE", "节点传输不可用", status_code=503)
        response = transport.apply(
            {
                "schema_version": 1,
                "node_id": str(node.pk),
                "generation": generation,
                "expected_previous_generation": previous_generation,
                "config": config,
                "action": "normal" if allow_security_rollback else "security",
            }
        )
        result = ApplyResult(
            applied_generation=int(response.get("applied_generation", 0)),
            config_test_passed=bool(response.get("config_test_passed")),
            service_restarted=bool(response.get("service_restarted")),
            rollback_performed=bool(response.get("rollback_performed")),
        )
        if result.rollback_performed and not allow_security_rollback:
            ManagedNode.objects.filter(pk=node.pk).update(
                security_state="ISOLATION_UNCONFIRMED"
            )
            raise DomainError(
                "SECURITY_ROLLBACK_FORBIDDEN",
                "安全配置失败时不得恢复已撤销身份",
                status_code=409,
            )
        if (
            result.applied_generation != generation
            or not result.config_test_passed
            or not result.service_restarted
        ):
            if not allow_security_rollback:
                ManagedNode.objects.filter(pk=node.pk).update(
                    security_state="ISOLATION_UNCONFIRMED"
                )
            raise DomainError(
                "NODE_CONFIG_APPLY_FAILED", "节点配置应用未完成", status_code=409
            )

        digest = _config_hash(config)
        with transaction.atomic():
            node = ManagedNode.objects.select_for_update().get(pk=node_id)
            if node.desired_generation != generation:
                raise DomainError(
                    "CONFIG_GENERATION_RACE", "节点期望 generation 已变化", status_code=409
                )
            node.applied_generation = generation
            node.applied_config_hash = digest
            node.save(
                update_fields=["applied_generation", "applied_config_hash", "updated_at"]
            )
            NodeConfigRevision.objects.update_or_create(
                node=node,
                generation=generation,
                defaults={
                    "config_hash": digest,
                    "xray_version": getattr(settings, "XRAY_PINNED_VERSION", "26.3.27"),
                    "installer_version": "1.0.0",
                    "bundle_hash": getattr(settings, "XRAY_BUNDLE_HASH", "external-verified"),
                    "usable": True,
                },
            )
        return result

    def capture_probe_sessions(
        self,
        node_id: UUID,
        *,
        credential_refs: list[UUID],
        operation_id: UUID,
    ) -> dict[UUID, str]:
        node = ManagedNode.objects.get(pk=node_id)
        self._scope(node, operation_id)
        if self.session_runner is None:
            raise DomainError("PROBE_RUNNER_UNAVAILABLE", "持续探测器未配置", status_code=503)
        return self.session_runner(node, credential_refs, operation_id)

    def probe(
        self,
        node_id: UUID,
        *,
        credential_ref: UUID,
        expect_accept: bool,
        operation_id: UUID,
    ) -> ProbeResult:
        node = ManagedNode.objects.get(pk=node_id)
        self._scope(node, operation_id)
        if self.probe_runner is None:
            raise DomainError("PROBE_RUNNER_UNAVAILABLE", "节点探测器未配置", status_code=503)
        result = self.probe_runner(node, credential_ref, expect_accept, operation_id)
        if result.accepted is not None and result.accepted != expect_accept:
            raise DomainError("PROBE_EXPECTATION_FAILED", "节点探测结果不符合预期", status_code=409)
        return result
