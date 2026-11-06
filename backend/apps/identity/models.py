import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import SuperAdminManager


class SuperAdmin(AbstractBaseUser, PermissionsMixin):
    """The sole interactive administrator for the private control plane."""

    username = models.CharField(max_length=150, unique=True)
    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=True)
    session_version = models.PositiveBigIntegerField(default=1)
    totp_secret_envelope = models.JSONField(null=True, blank=True)
    last_totp_step = models.BigIntegerField(default=-1)
    recovery_code_hashes = models.JSONField(default=list, blank=True)
    totp_confirmed_at = models.DateTimeField(null=True, blank=True)
    last_password_change_at = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = []
    objects = SuperAdminManager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(singleton_key=1), name="only_admin_slot_one"
            )
        ]

    def __str__(self):
        return self.username


class AdminSession(models.Model):
    """Index/metadata for Django's server-side session; never an auth authority."""

    admin = models.ForeignKey(SuperAdmin, on_delete=models.CASCADE, related_name="sessions")
    session_key_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    session_version = models.PositiveBigIntegerField()
    absolute_expires_at = models.DateTimeField(null=True, blank=True)
    last_step_up_at = models.DateTimeField(null=True, blank=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent_hash = models.CharField(max_length=64, blank=True, default="")


class MFAChallenge(models.Model):
    """Short-lived password challenge; possession does not authorize APIs."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admin = models.ForeignKey(SuperAdmin, on_delete=models.CASCADE, related_name="mfa_challenges")
    kind = models.CharField(max_length=32, default="password")
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    session_binding = models.CharField(max_length=64, blank=True, default="")
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["admin", "expires_at"])]


class ProviderIdentityNetworkSetting(models.Model):
    """Database override for cloud credential identity verification networking."""

    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    enabled = models.BooleanField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(singleton_key=1),
                name="provider_identity_network_singleton_key_one",
            )
        ]


class NodeStatusSyncSetting(models.Model):
    """Database-backed schedule for read-only cloud node status refreshes."""

    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    enabled = models.BooleanField(default=False)
    interval_minutes = models.PositiveSmallIntegerField(default=60)
    last_scheduled_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(singleton_key=1), name="node_status_sync_singleton_key_one"
            ),
            models.CheckConstraint(
                condition=models.Q(interval_minutes__gte=5, interval_minutes__lte=1440),
                name="node_status_sync_interval_range",
            ),
        ]


class NodeAutomationSetting(models.Model):
    """Database policy and local schedule state for automated node operations."""

    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    pool_sync_enabled = models.BooleanField(default=False)
    pool_sync_interval_minutes = models.PositiveSmallIntegerField(default=15)
    pool_sync_creation_templates = models.JSONField(default=list, blank=True)
    pool_sync_last_scheduled_at = models.DateTimeField(null=True, blank=True)
    daily_restart_enabled = models.BooleanField(default=False)
    daily_restart_time = models.CharField(max_length=5, default="04:00")
    daily_restart_timezone = models.CharField(max_length=64, default="Asia/Shanghai")
    daily_restart_last_local_date = models.DateField(null=True, blank=True)
    daily_restart_last_node_id = models.UUIDField(null=True, blank=True)
    daily_restart_last_success_node_id = models.UUIDField(null=True, blank=True)
    daily_restart_last_scheduled_at = models.DateTimeField(null=True, blank=True)
    usage_sync_enabled = models.BooleanField(default=True)
    usage_sync_interval_minutes = models.PositiveSmallIntegerField(default=1)
    usage_sync_last_scheduled_at = models.DateTimeField(null=True, blank=True)
    policy_version = models.PositiveBigIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(singleton_key=1),
                name="node_automation_singleton_key_one",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    pool_sync_interval_minutes__gte=5,
                    pool_sync_interval_minutes__lte=1440,
                ),
                name="node_automation_pool_interval_range",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    usage_sync_interval_minutes__gte=1,
                    usage_sync_interval_minutes__lte=1440,
                ),
                name="node_automation_usage_interval_range",
            ),
            models.CheckConstraint(
                condition=models.Q(policy_version__gte=1),
                name="node_automation_policy_version_positive",
            ),
        ]
