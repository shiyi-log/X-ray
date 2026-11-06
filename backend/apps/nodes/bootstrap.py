from __future__ import annotations

from uuid import UUID

from django.utils import timezone

from apps.operations.claims import assert_current, claim_operation, release_claim
from apps.operations.models import Operation, OperationStep
from common.errors import DomainError

from .models import ManagedNode


class NodeBootstrapService:
    """Fail closed until a pinned installer and firewall workflow are available."""

    @staticmethod
    def run(operation_id: UUID | str) -> None:
        operation = Operation.objects.get(pk=operation_id)
        if operation.status in Operation.TERMINAL_STATUSES:
            return
        claim = claim_operation(
            operation.pk,
            worker_id=f"node-bootstrap-{operation.pk}",
            lease_seconds=60,
        )
        try:
            operation = assert_current(claim)
            node = ManagedNode.objects.get(pk=operation.target_id)
            if (
                operation.kind != "node.bootstrap"
                or operation.target_type != "node"
                or node.cloud_credential_version_id != operation.cloud_credential_version_id
                or str(operation.params.get("region") or "") != node.region
                or str(operation.params.get("account_id") or "") != str(node.cloud_account_id)
            ):
                raise DomainError(
                    "OPERATION_TARGET_MISMATCH", "bootstrap 操作目标不匹配", status_code=409
                )
            if (
                node.desired_state != "PRESENT"
                or node.provisioning_state not in {"PROVISIONED", "RECONCILIATION"}
                or node.raw_cloud_state.casefold() != "running"
                or not node.external_id
            ):
                raise DomainError(
                    "NODE_NOT_BOOTSTRAPPABLE", "节点当前不能初始化", status_code=409
                )

            # The existing SSH agent only applies config to a previously installed
            # runtime. No pinned installer upload or read-before-write firewall
            # workflow exists, so creating credentials or marking READY is unsafe.
            blocked = DomainError(
                "BOOTSTRAP_INSTALLER_UNAVAILABLE",
                "缺少已验证的固定版本安装及防火墙配置流程",
                status_code=409,
            )
            attempt = OperationStep.objects.filter(
                operation=operation, name="bootstrap.preflight"
            ).count() + 1
            OperationStep.objects.create(
                operation=operation,
                name="bootstrap.preflight",
                phase="bootstrap",
                status="BLOCKED",
                attempt=attempt,
                evidence={
                    "error_code": blocked.code,
                    "pinned_installer_available": False,
                    "firewall_read_before_write_available": False,
                },
                started_at=timezone.now(),
                finished_at=timezone.now(),
            )
            Operation.objects.filter(pk=operation.pk).update(
                error_code=blocked.code,
                error_details={},
            )
            release_claim(claim, status="NEEDS_RECONCILIATION")
        except DomainError as exc:
            Operation.objects.filter(pk=operation.pk).update(
                error_code=exc.code,
                error_details={},
            )
            release_claim(claim, status="FAILED")
            return
        except Exception:
            Operation.objects.filter(pk=operation.pk).update(
                error_code="NODE_BOOTSTRAP_FAILED",
                error_details={},
            )
            release_claim(claim, status="FAILED")
            raise
