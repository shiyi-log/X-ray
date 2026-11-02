from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.nodes.models import ManagedNode, NodeProtocol


class AccessProfile(models.Model):
    STATUS_CHOICES = [
        ("ACTIVE", "Active"),
        ("REVOKING", "Revoking"),
        ("REVOKED", "Revoked"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, unique=True)
    plan = models.ForeignKey("SubscriptionPlan", null=True, blank=True, on_delete=models.PROTECT)
    expires_at = models.DateTimeField(null=True, blank=True)
    traffic_limit_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    upload_bytes = models.PositiveBigIntegerField(default=0)
    download_bytes = models.PositiveBigIntegerField(default=0)
    usage_updated_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ACTIVE")
    publishing_frozen = models.BooleanField(default=False)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def delete(self, *args, **kwargs):
        raise ValidationError("access profiles are retained for revocation history")


class NodeCredential(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(
        AccessProfile, on_delete=models.PROTECT, related_name="node_credentials"
    )
    node = models.ForeignKey(
        ManagedNode, on_delete=models.PROTECT, related_name="access_credentials"
    )
    protocol = models.ForeignKey(
        NodeProtocol, on_delete=models.PROTECT, related_name="access_credentials"
    )
    version = models.PositiveIntegerField()
    encrypted_material = models.JSONField()
    credential_scope = models.CharField(max_length=20, default="profile")
    desired_generation = models.PositiveBigIntegerField()
    applied_generation = models.PositiveBigIntegerField(default=0)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "node", "protocol", "version"],
                name="unique_profile_node_protocol_credential_version",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="positive_node_credential_version"
            ),
        ]

    def delete(self, *args, **kwargs):
        raise ValidationError("node credentials are retained for revocation history")


class SubscriptionPool(models.Model):
    """The single shared subscription pool used by all delivered tokens."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    name = models.CharField(max_length=120, default="default")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(singleton_key=1),
                name="subscription_pool_singleton_key_one",
            )
        ]

    def delete(self, *args, **kwargs):
        raise ValidationError("subscription pool is retained")


class Subscription(models.Model):
    STATUS_CHOICES = [("ACTIVE", "Active"), ("REVOKED", "Revoked")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pool = models.ForeignKey(
        SubscriptionPool, on_delete=models.PROTECT, related_name="subscriptions"
    )
    profile = models.OneToOneField(
        AccessProfile, on_delete=models.PROTECT, related_name="subscription"
    )
    token_digest = models.CharField(max_length=64, unique=True)
    token_epoch = models.PositiveBigIntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ACTIVE")
    current_revision = models.ForeignKey(
        "SubscriptionRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_for_subscriptions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def delete(self, *args, **kwargs):
        raise ValidationError("subscriptions are retained for token tombstones")


class SubscriptionToken(models.Model):
    STATUS_CHOICES = [
        ("ACTIVE", "Active"),
        ("REVOKED", "Revoked"),
        ("EXPIRED", "Expired"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(
        Subscription, on_delete=models.PROTECT, related_name="token_history"
    )
    token_digest = models.CharField(max_length=64, unique=True)
    token_epoch = models.PositiveBigIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ACTIVE")
    revoked_at = models.DateTimeField(null=True, blank=True)
    replaced_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="replaces"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "token_epoch"],
                name="unique_subscription_token_epoch",
            )
        ]

    def delete(self, *args, **kwargs):
        raise ValidationError("subscription token tombstones are permanent")


class RevocationTombstone(models.Model):
    token_digest = models.CharField(primary_key=True, max_length=64, editable=False)
    reason = models.CharField(max_length=120)
    source_event_id = models.CharField(max_length=128, blank=True, default="")
    source_sequence = models.PositiveBigIntegerField(null=True, blank=True)
    revoked_at = models.DateTimeField(default=timezone.now)
    imported_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            previous = type(self).objects.get(pk=self.pk)
            immutable = ("reason", "source_event_id", "source_sequence", "revoked_at")
            if any(getattr(previous, field) != getattr(self, field) for field in immutable):
                raise ValidationError("revocation tombstones are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("revocation tombstones are permanent")


class SubscriptionRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(
        Subscription, on_delete=models.PROTECT, related_name="revisions"
    )
    number = models.PositiveBigIntegerField()
    public_version = models.CharField(max_length=64, unique=True)
    payloads = models.JSONField(default=dict)
    payload_hashes = models.JSONField(default=dict)
    unavailable_reasons = models.JSONField(default=dict, blank=True)
    node_versions = models.JSONField(default=dict)
    published_at = models.DateTimeField(auto_now_add=True)
    usable = models.BooleanField(default=True)
    invalidated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "number"],
                name="unique_subscription_revision_number",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous:
                immutable = (
                    "subscription_id",
                    "number",
                    "public_version",
                    "payloads",
                    "payload_hashes",
                    "unavailable_reasons",
                    "node_versions",
                    "published_at",
                )
                if any(getattr(previous, field) != getattr(self, field) for field in immutable):
                    raise ValidationError("subscription revisions are immutable")
                if previous.usable is False and self.usable is True:
                    raise ValidationError("invalidated revisions cannot become usable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("subscription revisions are retained")


class PublicationBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    excluded_node = models.ForeignKey(ManagedNode, null=True, blank=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=30, default="PREPARING")
    subscription_ids = models.JSONField(default=list)
    result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)


class SecurityState(models.Model):
    MODE_CHOICES = [("OPEN", "Open"), ("MAINTENANCE", "Maintenance")]

    singleton_key = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default="OPEN")
    last_security_sequence = models.PositiveBigIntegerField(default=0)
    expected_security_sequence = models.PositiveBigIntegerField(default=0)
    last_external_security_sequence = models.PositiveBigIntegerField(default=0)
    security_backup_lagging = models.BooleanField(default=False)
    restore_epoch = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(singleton_key=1), name="only_security_state_slot_one"
            )
        ]


class SecurityEventRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sequence = models.PositiveBigIntegerField(unique=True)
    event_id = models.CharField(max_length=128, unique=True)
    previous_digest = models.CharField(max_length=64, default="0" * 64)
    digest = models.CharField(max_length=64)
    kind = models.CharField(max_length=80)
    verified = models.BooleanField(default=False)
    payload = models.JSONField(default=dict)
    restore_epoch = models.PositiveBigIntegerField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence"]

    def delete(self, *args, **kwargs):
        raise ValidationError("security event records are retained")


class SecurityEventOutbox(models.Model):
    event = models.OneToOneField(
        SecurityEventRecord,
        on_delete=models.PROTECT,
        related_name="external_outbox",
    )
    payload = models.JSONField()
    attempts = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now)
    delivered_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["delivered_at", "available_at"])]

    def delete(self, *args, **kwargs):
        raise ValidationError("security event outbox records are retained")


class RevocationNodeState(models.Model):
    STATUS_CHOICES = [
        ("REQUESTED", "Requested"),
        ("APPLYING", "Applying"),
        ("CONFIG_APPLIED", "Config applied"),
        ("SERVICE_RESTARTED", "Service restarted"),
        ("VERIFIED_REVOKED", "Verified revoked"),
        ("QUARANTINED", "Quarantined"),
        ("REVOCATION_UNCONFIRMED", "Revocation unconfirmed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operation = models.ForeignKey(
        "operations.Operation", on_delete=models.PROTECT, related_name="revocation_nodes"
    )
    node = models.ForeignKey(
        ManagedNode, on_delete=models.PROTECT, related_name="revocation_states"
    )
    status = models.CharField(max_length=40, choices=STATUS_CHOICES, default="REQUESTED")
    credential_refs = models.JSONField(default=list)
    target_generation = models.PositiveBigIntegerField(default=0)
    evidence = models.JSONField(default=dict, blank=True)
    last_error_code = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["operation", "node"], name="unique_revocation_operation_node"
            )
        ]


class SecretDeliveryReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(
        Subscription, on_delete=models.PROTECT, related_name="delivery_receipts"
    )
    token_epoch = models.PositiveBigIntegerField()
    token_digest = models.CharField(max_length=64)
    kind = models.CharField(max_length=20)
    delivered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "token_epoch"],
                name="unique_subscription_delivery_epoch",
            )
        ]


class SubscriptionPlan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, unique=True)
    traffic_limit_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    duration_days = models.PositiveIntegerField(null=True, blank=True)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class UsageCheckpoint(models.Model):
    node = models.ForeignKey(ManagedNode, on_delete=models.PROTECT)
    profile = models.ForeignKey(AccessProfile, on_delete=models.PROTECT)
    epoch = models.CharField(max_length=120)
    sequence = models.PositiveBigIntegerField(default=0)
    upload_bytes = models.PositiveBigIntegerField(default=0)
    download_bytes = models.PositiveBigIntegerField(default=0)
    sampled_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["node", "profile", "epoch"], name="unique_usage_checkpoint"
            )
        ]


class SubscriptionMutation(models.Model):
    key = models.UUIDField(primary_key=True)
    scope = models.CharField(max_length=160)
    request_hash = models.CharField(max_length=64)
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
