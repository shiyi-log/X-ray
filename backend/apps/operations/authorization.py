from __future__ import annotations

from django.utils import timezone

from common.errors import DomainError
from providers.base import AccountRef, MutationPermit

from .claims import Claim, assert_current


class DatabaseWriteAuthorizer:
    """Revalidates the DB lease and immutable operation scope before every SDK write."""

    def __init__(self, claim: Claim):
        self.claim = claim

    @staticmethod
    def _is_authorized_recovery(operation) -> bool:
        if operation.kind != "security.recovery.quarantine":
            return False
        from apps.subscriptions.security_barrier import SecurityBarrier

        preview = operation.preview
        state = SecurityBarrier.state()
        return bool(
            preview
            and preview.consumed_at is not None
            and preview.kind == operation.kind
            and preview.target_id == operation.target_id
            and preview.required_phrase == "RECOVERY QUARANTINE"
            and operation.params.get("confirmation") == preview.required_phrase
            and preview.snapshot.get("restore_epoch") == state.restore_epoch
        )

    def assert_allowed(
        self,
        permit: MutationPermit,
        *,
        action: str,
        account: AccountRef,
        resource_id: str | None,
    ) -> None:
        operation = assert_current(self.claim)
        if not self._is_authorized_recovery(operation):
            from apps.subscriptions.security_barrier import (
                PublishingBlocked,
                SecurityBarrier,
            )

            try:
                SecurityBarrier.assert_open(purpose="cloud_write")
            except PublishingBlocked as exc:
                raise DomainError(
                    "SECURITY_BARRIER_CLOSED",
                    "恢复屏障关闭期间禁止云写入",
                    status_code=503,
                ) from exc
        if operation.status != "RUNNING":
            raise DomainError("CLOUD_WRITE_NOT_AUTHORIZED", "操作不在运行状态", status_code=403)
        if permit.operation_id != operation.pk or permit.fence != operation.lease_fence:
            raise DomainError(
                "CLOUD_WRITE_NOT_AUTHORIZED", "Operation fence 不匹配", status_code=403
            )
        if permit.operation_key != str(operation.idempotency_key):
            raise DomainError("CLOUD_WRITE_NOT_AUTHORIZED", "Operation key 不匹配", status_code=403)
        if permit.expires_at <= timezone.now():
            raise DomainError("CLOUD_WRITE_NOT_AUTHORIZED", "写授权已过期", status_code=403)
        if permit.action != action or permit.account_id != account.id:
            raise DomainError("CLOUD_WRITE_NOT_AUTHORIZED", "写授权范围不匹配", status_code=403)
        if permit.external_account_id != account.external_account_id:
            raise DomainError("CLOUD_WRITE_NOT_AUTHORIZED", "云身份不匹配", status_code=403)
        expected_region = str(operation.params.get("region") or "")
        if not expected_region or permit.region != expected_region:
            raise DomainError("CLOUD_WRITE_NOT_AUTHORIZED", "云区域不匹配", status_code=403)
        if permit.resource_id != resource_id:
            raise DomainError("CLOUD_WRITE_NOT_AUTHORIZED", "云资源不匹配", status_code=403)
        if operation.cloud_credential_version_id and (
            operation.cloud_credential_version.account_id != account.id
            or operation.cloud_credential_version.version != account.credential_version
        ):
            raise DomainError("CLOUD_WRITE_NOT_AUTHORIZED", "云凭据版本不匹配", status_code=403)

        automation = operation.params.get("automation")
        if automation is not None and action in {"delete", "reboot"}:
            if operation.target_type != "node":
                raise DomainError(
                    "AUTOMATION_TARGET_INVALID", "自动化目标无效", status_code=409
                )
            from apps.nodes.models import ManagedNode

            node = ManagedNode.objects.filter(pk=operation.target_id).first()
            if node is None:
                raise DomainError(
                    "AUTOMATION_TARGET_INVALID", "自动化目标无效", status_code=409
                )
            policy_version = (
                automation.get("policy_version") if isinstance(automation, dict) else None
            )
            if (
                not isinstance(policy_version, int)
                or isinstance(policy_version, bool)
                or policy_version < 1
            ):
                raise DomainError(
                    "AUTOMATION_POLICY_INVALID", "自动化策略版本无效", status_code=409
                )
            try:
                if action == "delete" and operation.kind == "node.delete":
                    from apps.nodes.automation import validate_automated_delete

                    if not isinstance(automation, dict) or automation.get("kind") != "pool_sync":
                        raise DomainError(
                            "AUTOMATION_POLICY_INVALID", "自动化策略无效", status_code=409
                        )
                    validate_automated_delete(operation, node, policy_version)
                elif action == "reboot" and operation.kind == "node.reboot":
                    from apps.nodes.automation import validate_automated_restart

                    if (
                        not isinstance(automation, dict)
                        or automation.get("kind") != "daily_restart"
                    ):
                        raise DomainError(
                            "AUTOMATION_POLICY_INVALID", "自动化策略无效", status_code=409
                        )
                    validate_automated_restart(operation, node, policy_version)
                else:
                    raise DomainError(
                        "AUTOMATION_ACTION_INVALID", "自动化操作类型无效", status_code=409
                    )
            except DomainError:
                raise
            except Exception as exc:
                code = (
                    "AUTOMATED_DELETE_VALIDATION_FAILED"
                    if action == "delete"
                    else "AUTOMATED_RESTART_VALIDATION_FAILED"
                )
                raise DomainError(code, "自动化策略核验失败", status_code=409) from exc
