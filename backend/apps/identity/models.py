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
