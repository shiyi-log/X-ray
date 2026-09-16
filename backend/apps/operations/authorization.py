from __future__ import annotations

from django.utils import timezone

from common.errors import DomainError
from providers.base import AccountRef, MutationPermit

from .claims import Claim, assert_current


class DatabaseWriteAuthorizer:
    """Revalidates the DB lease and immutable operation scope before every SDK write."""

    def __init__(self, claim: Claim):
        self.claim = claim

    def assert_allowed(
        self,
        permit: MutationPermit,
        *,
        action: str,
        account: AccountRef,
        resource_id: str | None,
    ) -> None:
        operation = assert_current(self.claim)
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
