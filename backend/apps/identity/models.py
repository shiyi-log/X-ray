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
