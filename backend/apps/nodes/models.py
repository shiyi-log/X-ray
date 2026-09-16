from __future__ import annotations

import uuid

from django.db import models

from apps.cloud_accounts.models import CloudAccount, CloudCredentialVersion


class NodePool(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, unique=True)
    quota = models.PositiveIntegerField(default=3)
    allow_create = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quota__gte=1), name="node_pool_quota_positive"
            )
        ]


class ManagedNode(models.Model):
    DESIRED_CHOICES = [
        ("PRESENT", "Present"),
        ("STOPPED", "Stopped"),
        ("DELETED", "Deleted"),
    ]
    SECURITY_CHOICES = [
        ("OPEN", "Open"),
        ("REVOKING", "Revoking"),
        ("REVOCATION_UNCONFIRMED", "Revocation unconfirmed"),
        ("ISOLATION_UNCONFIRMED", "Isolation unconfirmed"),
        ("QUARANTINED", "Quarantined"),
        ("MAINTENANCE", "Maintenance"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pool = models.ForeignKey(NodePool, on_delete=models.PROTECT, related_name="nodes")
    cloud_account = models.ForeignKey(
        CloudAccount, on_delete=models.PROTECT, related_name="managed_nodes"
    )
    cloud_credential_version = models.ForeignKey(
        CloudCredentialVersion, on_delete=models.PROTECT, related_name="managed_nodes"
    )
    region = models.CharField(max_length=120)
    plan_id = models.CharField(max_length=160)
    image_id = models.CharField(max_length=160)
    deterministic_name = models.CharField(max_length=180, unique=True)
    operation_key = models.UUIDField()
    external_id = models.CharField(max_length=200, blank=True, default="")
    addresses = models.JSONField(default=list, blank=True)
    raw_cloud_state = models.CharField(max_length=100, blank=True, default="")
    desired_state = models.CharField(max_length=32, choices=DESIRED_CHOICES, default="PRESENT")
    provisioning_state = models.CharField(max_length=40, default="RESERVED")
    health_state = models.CharField(max_length=40, default="UNKNOWN")
    security_state = models.CharField(max_length=40, choices=SECURITY_CHOICES, default="OPEN")
    consumes_quota = models.BooleanField(default=True)
    desired_generation = models.PositiveBigIntegerField(default=0)
    applied_generation = models.PositiveBigIntegerField(default=0)
    applied_config_hash = models.CharField(max_length=64, blank=True, default="")
    observed_at = models.DateTimeField(null=True, blank=True)
    observation_error = models.CharField(max_length=100, blank=True, default="")
    last_error_code = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["pool", "consumes_quota"]),
            models.Index(fields=["cloud_account", "region", "external_id"]),
        ]


class NodeResource(models.Model):
    KIND_CHOICES = [
        ("instance", "Instance"),
        ("static_ip", "Static IP"),
        ("firewall", "Firewall"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    node = models.ForeignKey(ManagedNode, on_delete=models.PROTECT, related_name="resources")
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    external_id = models.CharField(max_length=200)
    request_id = models.CharField(max_length=160, blank=True, default="")
    ownership_tags = models.JSONField(default=dict)
    cost_status = models.CharField(max_length=40, default="UNKNOWN")
    releasable = models.BooleanField(default=False)
    released_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["node", "kind", "external_id"],
                name="unique_node_resource",
            )
        ]


class NodeProtocol(models.Model):
    PROTOCOL_CHOICES = [
        ("shadowsocks", "Shadowsocks"),
        ("socks5", "SOCKS5"),
        ("vmess", "VMess"),
        ("vless", "VLESS"),
        ("trojan", "Trojan"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    node = models.ForeignKey(ManagedNode, on_delete=models.CASCADE, related_name="protocols")
    protocol = models.CharField(max_length=32, choices=PROTOCOL_CHOICES)
    listen_address = models.CharField(max_length=64, default="0.0.0.0")
    port = models.PositiveIntegerField()
    network = models.CharField(max_length=16, default="tcp")
    transport = models.CharField(max_length=32, default="tcp")
    tls_enabled = models.BooleanField(default=False)
    server_name = models.CharField(max_length=253, blank=True, default="")
    certificate_ref = models.CharField(max_length=253, blank=True, default="")
    method = models.CharField(max_length=80, blank=True, default="")
    credential_scope = models.CharField(max_length=20, default="profile")
    enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["node", "port", "network"], name="unique_node_port")
        ]


class HostKeyRecord(models.Model):
    STATUS_CHOICES = [
        ("CANDIDATE", "Candidate"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("SUPERSEDED", "Superseded"),
    ]

    node = models.ForeignKey(ManagedNode, on_delete=models.CASCADE, related_name="host_keys")
    fingerprint = models.CharField(max_length=160)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="CANDIDATE")
    source = models.CharField(max_length=80)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["node", "fingerprint"], name="unique_node_host_fingerprint"
            ),
            models.UniqueConstraint(
                fields=["node"],
                condition=models.Q(status="APPROVED"),
                name="one_approved_host_key_per_node",
            ),
        ]


class NodeConfigRevision(models.Model):
    node = models.ForeignKey(ManagedNode, on_delete=models.PROTECT, related_name="config_revisions")
    generation = models.PositiveBigIntegerField()
    config_hash = models.CharField(max_length=64)
    xray_version = models.CharField(max_length=40)
    installer_version = models.CharField(max_length=40)
    bundle_hash = models.CharField(max_length=64)
    deployed_at = models.DateTimeField(null=True, blank=True)
    probe_result = models.JSONField(default=dict, blank=True)
    usable = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["node", "generation"], name="unique_node_config_generation"
            )
        ]
