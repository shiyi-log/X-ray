from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import AuditService
from common.errors import DomainError

from .models import ActionPreview, Operation, OutboxEvent


def canonical_hash(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def preview_params(params: dict) -> dict:
    """Confirmation proves intent but is not part of the previewed resource snapshot."""
    return {key: value for key, value in params.items() if key != "confirmation"}


class ActionPreviewService:
    @staticmethod
    def create(
        *,
        admin,
        kind: str,
        target_id: UUID,
        params: dict,
        snapshot: dict | None = None,
        required_phrase: str,
    ) -> ActionPreview:
        return ActionPreview.objects.create(
            admin=admin,
            kind=kind,
            target_id=target_id,
            params_hash=canonical_hash(preview_params(params)),
            snapshot=snapshot or {},
            required_phrase=required_phrase,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

    @staticmethod
    def validate(
        preview_id: UUID,
        *,
        admin,
        kind: str,
        target_id: UUID,
        params: dict,
        confirmation: str | None = None,
    ) -> ActionPreview:
        try:
            preview = ActionPreview.objects.select_for_update().get(pk=preview_id)
        except ActionPreview.DoesNotExist as exc:
            raise DomainError("PREVIEW_NOT_FOUND", "危险操作预览不存在", status_code=409) from exc
        if preview.admin_id != admin.pk or preview.kind != kind or preview.target_id != target_id:
            raise DomainError(
                "PREVIEW_BINDING_MISMATCH", "危险操作预览与目标不匹配", status_code=409
            )
        if preview.params_hash != canonical_hash(preview_params(params)):
            raise DomainError("PREVIEW_STALE", "操作参数已改变，请重新预览", status_code=409)
        if preview.expires_at <= timezone.now() or preview.consumed_at:
            raise DomainError("PREVIEW_EXPIRED", "危险操作预览已过期", status_code=409)
        if confirmation is not None and confirmation != preview.required_phrase:
            raise DomainError("CONFIRMATION_MISMATCH", "确认文本不匹配", status_code=409)
        return preview


class OperationService:
    @staticmethod
    def submit(
        *,
        kind: str,
        target_id: UUID,
        params: dict,
        key: UUID,
        preview_id: UUID | None,
        admin=None,
        target_type: str = "node",
        cloud_credential_version=None,
    ) -> Operation:
        if admin is None:
            from apps.identity.models import SuperAdmin

            admin = SuperAdmin.objects.get(singleton_key=1)
        request_payload = {
            "kind": kind,
            "target_type": target_type,
            "target_id": str(target_id),
            "params": params,
            "preview_id": str(preview_id) if preview_id else None,
        }
        request_hash = canonical_hash(request_payload)
        existing = Operation.objects.filter(
            admin=admin,
            kind=kind,
            target_id=target_id,
            idempotency_key=key,
        ).first()
        if existing:
            if existing.request_hash != request_hash:
                raise DomainError(
                    "IDEMPOTENCY_CONFLICT",
                    "同一幂等键对应的参数不同",
                    status_code=409,
                )
            return existing
        try:
            with transaction.atomic():
                preview = None
                if preview_id:
                    preview = ActionPreviewService.validate(
                        preview_id,
                        admin=admin,
                        kind=kind,
                        target_id=target_id,
                        params=params,
                        confirmation=params.get("confirmation"),
                    )
                operation = Operation.objects.create(
                    admin=admin,
                    kind=kind,
                    target_type=target_type,
                    target_id=target_id,
                    params=params,
                    request_hash=request_hash,
                    idempotency_key=key,
                    preview=preview,
                    cloud_credential_version=cloud_credential_version,
                )
                OutboxEvent.objects.create(
                    operation=operation,
                    schema_version=1,
                    available_at=timezone.now(),
                )
                if preview:
                    preview.consumed_at = timezone.now()
                    preview.save(update_fields=["consumed_at"])
                AuditService.append(
                    action=f"operation.submit.{kind}",
                    target_type=target_type,
                    target_id=target_id,
                    result="ACCEPTED",
                    metadata={"operation_id": str(operation.pk)},
                    actor=admin,
                )
                return operation
        except IntegrityError:
            existing = Operation.objects.get(
                admin=admin,
                kind=kind,
                target_id=target_id,
                idempotency_key=key,
            )
            if existing.request_hash != request_hash:
                raise DomainError(
                    "IDEMPOTENCY_CONFLICT",
                    "同一幂等键对应的参数不同",
                    status_code=409,
                )
            return existing

    @staticmethod
    def cancel(operation_id: UUID, *, admin) -> Operation:
        with transaction.atomic():
            operation = Operation.objects.select_for_update().get(
                pk=operation_id, admin=admin
            )
            if not operation.can_cancel:
                raise DomainError(
                    "OPERATION_NOT_CANCELLABLE",
                    "操作已越过可取消检查点",
                    status_code=409,
                )
            if operation.status == "PENDING":
                operation.status = "CANCELLED"
            elif operation.status in {"RUNNING", "RETRY_PENDING"}:
                operation.status = "CANCELLING"
            else:
                raise DomainError("OPERATION_NOT_CANCELLABLE", "当前状态不能取消", status_code=409)
            operation.save(update_fields=["status", "updated_at"])
            return operation

    @staticmethod
    def retry(operation_id: UUID, *, admin) -> Operation:
        with transaction.atomic():
            operation = Operation.objects.select_for_update().get(
                pk=operation_id, admin=admin
            )
            if operation.status not in {
                "PARTIALLY_SUCCEEDED",
                "NEEDS_RECONCILIATION",
            }:
                raise DomainError(
                    "OPERATION_NOT_RETRYABLE",
                    "当前状态不能重试",
                    status_code=409,
                )
            operation.status = "RETRY_PENDING"
            operation.error_code = ""
            operation.error_details = {}
            operation.lease_owner = ""
            operation.lease_expires_at = None
            operation.save(
                update_fields=[
                    "status",
                    "error_code",
                    "error_details",
                    "lease_owner",
                    "lease_expires_at",
                    "updated_at",
                ]
            )
            if not OutboxEvent.objects.filter(
                operation=operation, delivered_at__isnull=True
            ).exists():
                OutboxEvent.objects.create(
                    operation=operation,
                    schema_version=operation.schema_version,
                    available_at=timezone.now(),
                )
            AuditService.append(
                action=f"operation.retry.{operation.kind}",
                target_type=operation.target_type,
                target_id=operation.target_id,
                result="ACCEPTED",
                metadata={"operation_id": str(operation.pk)},
                actor=admin,
            )
            return operation
