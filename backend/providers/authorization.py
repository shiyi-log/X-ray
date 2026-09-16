from __future__ import annotations

from datetime import UTC, datetime

from common.errors import DomainError

from .base import AccountRef, Action, MutationPermit


class DenyWrites:
    """Default authorizer: a read-only process can never mutate cloud state."""

    def assert_allowed(
        self,
        permit: MutationPermit,
        *,
        action: Action,
        account: AccountRef,
        resource_id: str | None,
    ) -> None:
        raise DomainError(
            "CLOUD_WRITE_NOT_AUTHORIZED",
            "云写入未获得受信任的 Operation 授权",
            status_code=403,
        )


class StaticWriteAuthorizer:
    """Small test authorizer; production P3 replaces it with a DB-backed checker."""

    def __init__(self, allowed: MutationPermit):
        self.allowed = allowed

    def assert_allowed(
        self,
        permit: MutationPermit,
        *,
        action: Action,
        account: AccountRef,
        resource_id: str | None,
    ) -> None:
        if permit is None or permit != self.allowed:
            raise DomainError("CLOUD_WRITE_NOT_AUTHORIZED", "写入授权不匹配", status_code=403)
        if permit.action != action or permit.account_id != account.id:
            raise DomainError("CLOUD_WRITE_NOT_AUTHORIZED", "写入授权范围不匹配", status_code=403)
        if permit.external_account_id != account.external_account_id:
            raise DomainError("CLOUD_WRITE_NOT_AUTHORIZED", "云账号归属不匹配", status_code=403)
        if not permit.region:
            raise DomainError("CLOUD_WRITE_NOT_AUTHORIZED", "云区域未绑定", status_code=403)
        if permit.expires_at <= datetime.now(UTC):
            raise DomainError("CLOUD_WRITE_NOT_AUTHORIZED", "写入授权已过期", status_code=403)
