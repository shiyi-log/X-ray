from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models


class CloudAccount(models.Model):
    PROVIDER_CHOICES = [
        ("aws_lightsail", "AWS Lightsail"),
        ("aliyun_swas", "Alibaba SWAS"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES)
    external_account_id = models.CharField(max_length=160)
    credential_version = models.PositiveIntegerField(default=1)
    enabled = models.BooleanField(default=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    last_validation_code = models.CharField(max_length=80, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(provider__in=["aws_lightsail", "aliyun_swas"]),
                name="valid_cloud_provider",
            ),
            models.UniqueConstraint(
                fields=["provider", "external_account_id"],
                name="unique_cloud_provider_external_account",
            ),
        ]
        ordering = ["name", "id"]

    def __str__(self):
        return f"{self.name} ({self.provider})"

    def delete(self, *args, **kwargs):
        raise ValidationError("cloud accounts are not hard-deletable")


class CloudCredentialVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(
        CloudAccount,
        on_delete=models.PROTECT,
        related_name="credential_versions",
    )
    version = models.PositiveIntegerField()
    encrypted_credentials = models.JSONField()
    identity_verified_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="positive_cloud_credential_version",
            ),
            models.UniqueConstraint(
                fields=["account", "version"],
                name="unique_cloud_credential_version",
            ),
        ]
        ordering = ["account", "version"]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("credential versions are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("credential versions are retained for reconciliation")
