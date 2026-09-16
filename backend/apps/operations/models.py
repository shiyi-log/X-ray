from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.cloud_accounts.models import CloudCredentialVersion


class ActionPreview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admin = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=80)
    target_id = models.UUIDField()
    params_hash = models.CharField(max_length=64)
    snapshot = models.JSONField(default=dict)
    required_phrase = models.CharField(max_length=120)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Operation(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("RUNNING", "Running"),
        ("RETRY_PENDING", "Retry pending"),
        ("CANCELLING", "Cancelling"),
        ("CANCELLED", "Cancelled"),
        ("SUCCEEDED", "Succeeded"),
        ("FAILED", "Failed"),
        ("PARTIALLY_SUCCEEDED", "Partially succeeded"),
        ("NEEDS_RECONCILIATION", "Needs reconciliation"),
    ]
    TERMINAL_STATUSES = {"CANCELLED", "SUCCEEDED", "FAILED", "PARTIALLY_SUCCEEDED"}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admin = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=80)
    target_type = models.CharField(max_length=80, default="node")
    target_id = models.UUIDField()
    params = models.JSONField(default=dict)
    request_hash = models.CharField(max_length=64)
    idempotency_key = models.UUIDField()
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="PENDING")
    current_step = models.CharField(max_length=120, blank=True, default="")
    can_cancel = models.BooleanField(default=True)
    preview = models.ForeignKey(
        ActionPreview, null=True, blank=True, on_delete=models.PROTECT, related_name="operations"
    )
    cloud_credential_version = models.ForeignKey(
        CloudCredentialVersion,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="operations",
    )
    lease_owner = models.CharField(max_length=120, blank=True, default="")
    lease_fence = models.PositiveBigIntegerField(default=0)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=100, blank=True, default="")
    error_details = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    schema_version = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["admin", "kind", "target_id", "idempotency_key"],
                name="unique_operation_idempotency_scope",
            )
        ]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["target_type", "target_id", "status"]),
        ]


class OperationStep(models.Model):
    operation = models.ForeignKey(Operation, on_delete=models.CASCADE, related_name="steps")
    name = models.CharField(max_length=120)
    phase = models.CharField(max_length=80)
    status = models.CharField(max_length=40)
    attempt = models.PositiveIntegerField(default=1)
    external_request_id = models.CharField(max_length=160, blank=True, default="")
    result = models.JSONField(default=dict, blank=True)
    evidence = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["operation", "name", "attempt"],
                name="unique_operation_step_attempt",
            )
        ]
        ordering = ["created_at", "id"]


class OutboxEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operation = models.ForeignKey(Operation, on_delete=models.CASCADE, related_name="outbox_events")
    schema_version = models.PositiveSmallIntegerField(default=1)
    attempts = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField()
    delivered_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["delivered_at", "available_at"])]
