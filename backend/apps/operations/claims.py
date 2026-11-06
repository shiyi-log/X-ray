from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from common.errors import DomainError

from .models import Operation


@dataclass(frozen=True, slots=True)
class Claim:
    operation_id: UUID
    owner: str
    fence: int
    expires_at: object


def claim_operation(operation_id: UUID, *, worker_id: str, lease_seconds: int = 60) -> Claim:
    now = timezone.now()
    with transaction.atomic():
        operation = Operation.objects.select_for_update().get(pk=operation_id)
        if operation.status in Operation.TERMINAL_STATUSES:
            raise DomainError("OPERATION_TERMINAL", "终态操作不能再次领取", status_code=409)
        if (
            operation.lease_expires_at
            and operation.lease_expires_at > now
            and operation.lease_owner
            and operation.lease_owner != worker_id
        ):
            raise DomainError(
                "OPERATION_LEASED",
                "操作正在由其他 worker 执行",
                retryable=True,
                status_code=409,
            )
        operation.lease_fence += 1
        operation.lease_owner = worker_id
        operation.lease_expires_at = now + timedelta(seconds=lease_seconds)
        if operation.status in {"PENDING", "RETRY_PENDING"}:
            operation.status = "RUNNING"
        operation.save(
            update_fields=[
                "lease_fence",
                "lease_owner",
                "lease_expires_at",
                "status",
                "updated_at",
            ]
        )
        return Claim(operation.pk, worker_id, operation.lease_fence, operation.lease_expires_at)


def assert_current(claim: Claim) -> Operation:
    try:
        operation = Operation.objects.get(pk=claim.operation_id)
    except Operation.DoesNotExist as exc:
        raise DomainError("OPERATION_NOT_FOUND", "操作不存在", status_code=404) from exc
    if (
        operation.lease_owner != claim.owner
        or operation.lease_fence != claim.fence
        or operation.lease_expires_at is None
        or operation.lease_expires_at <= timezone.now()
    ):
        raise DomainError("STALE_OPERATION_FENCE", "worker 租约或 fence 已失效", status_code=409)
    return operation


def renew_claim(claim: Claim, *, lease_seconds: int = 60) -> Claim:
    with transaction.atomic():
        operation = Operation.objects.select_for_update().get(pk=claim.operation_id)
        assert_current(claim)
        now = timezone.now()
        operation.lease_expires_at = now + timedelta(seconds=lease_seconds)
        operation.save(update_fields=["lease_expires_at", "updated_at"])
        return Claim(
            operation.pk,
            claim.owner,
            claim.fence,
            operation.lease_expires_at,
        )


def release_claim(claim: Claim, *, status: str | None = None) -> Operation:
    with transaction.atomic():
        operation = Operation.objects.select_for_update().get(pk=claim.operation_id)
        assert_current(claim)
        operation.lease_owner = ""
        operation.lease_expires_at = None
        if status:
            operation.status = status
        operation.save(
            update_fields=["lease_owner", "lease_expires_at", "status", "updated_at"]
        )
        return operation
