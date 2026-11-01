from __future__ import annotations

from collections import defaultdict
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from apps.nodes.executor import NodeExecutor
from apps.nodes.models import ManagedNode, NodeProtocol
from apps.operations.claims import assert_current, claim_operation, release_claim
from apps.operations.models import Operation
from apps.operations.services import OperationService
from common.errors import DomainError

from .credentials import CredentialService, decrypt_material
from .models import AccessProfile, NodeCredential, SubscriptionRevision
from .policy import assert_entitled, quota_state
from .security_barrier import SecurityBarrier


def configured_factory():
    path = getattr(settings, "XRAY_NODE_TRANSPORT_FACTORY", "")
    if not path:
        raise DomainError(
            "NODE_EXECUTOR_UNAVAILABLE", "节点传输未配置，访问配置仍待下发", status_code=503
        )
    return import_string(path)


def build_node_config(node):
    latest = {}
    for c in (
        NodeCredential.objects.filter(
            node=node, revoked_at__isnull=True, protocol__enabled=True, profile__status="ACTIVE"
        )
        .select_related("protocol", "profile")
        .order_by("version")
    ):
        if quota_state(c.profile) == "ACTIVE":
            latest[(c.profile_id, c.protocol_id)] = c
    grouped = defaultdict(list)
    for c in latest.values():
        grouped[c.protocol_id].append(c)
    inbounds = []
    for credentials in grouped.values():
        p = credentials[0].protocol
        materials = [(c, decrypt_material(c)) for c in credentials]
        def email(c):
            return f"profile-{c.profile_id}"
        if p.protocol in {"vmess", "vless"}:
            config = {"clients": [{"id": m["id"], "email": email(c)} for c, m in materials]}
            if p.protocol == "vless":
                config["decryption"] = "none"
        elif p.protocol == "trojan":
            if not p.tls_enabled or not p.server_name or not p.certificate_ref:
                raise DomainError(
                    "TLS_CONFIGURATION_REQUIRED", "Trojan 需要服务器证书配置", status_code=409
                )
            config = {
                "clients": [{"password": m["password"], "email": email(c)} for c, m in materials]
            }
        elif p.protocol == "socks5":
            config = {
                "auth": "password",
                "udp": True,
                "accounts": [{"user": m["username"], "pass": m["password"]} for c, m in materials],
            }
            # SOCKS accounts have no per-user email stats; never invent user usage.
        else:
            config = {
                "network": "tcp,udp",
                "clients": [
                    {"method": m["method"], "password": m["password"], "email": email(c)}
                    for c, m in materials
                ],
            }
        stream = {"network": p.transport}
        if p.tls_enabled:
            if not p.certificate_ref.startswith(
                "/usr/local/etc/xray/certs/"
            ) or ".." in p.certificate_ref.split("/"):
                raise DomainError(
                    "TLS_CONFIGURATION_REQUIRED", "证书必须位于节点专用证书目录", status_code=409
                )
            stream.update(
                {
                    "security": "tls",
                    "tlsSettings": {
                        "serverName": p.server_name,
                        "certificates": [
                            {
                                "certificateFile": p.certificate_ref + ".crt",
                                "keyFile": p.certificate_ref + ".key",
                            }
                        ],
                    },
                }
            )
        if p.transport == "ws":
            stream["wsSettings"] = {"path": "/"}
        if p.transport == "grpc":
            stream["grpcSettings"] = {"serviceName": "xray"}
        inbounds.append(
            {
                "tag": f"protocol-{p.pk}",
                "listen": p.listen_address,
                "port": p.port,
                "protocol": "socks" if p.protocol == "socks5" else p.protocol,
                "settings": config,
                "streamSettings": stream,
            }
        )
    # The statistics endpoint is local to the node and never exposed publicly.
    inbounds.append(
        {
            "tag": "manager-api",
            "listen": "127.0.0.1",
            "port": 10085,
            "protocol": "dokodemo-door",
            "settings": {"address": "127.0.0.1"},
        }
    )
    return {
        "log": {"loglevel": "warning"},
        "inbounds": inbounds,
        "outbounds": [{"protocol": "freedom", "tag": "direct"}],
        "stats": {},
        "api": {"tag": "manager-api-out", "services": ["StatsService"]},
        "routing": {
            "rules": [
                {"type": "field", "inboundTag": ["manager-api"], "outboundTag": "manager-api-out"}
            ]
        },
        "policy": {"levels": {"0": {"statsUserUplink": True, "statsUserDownlink": True}}},
    }


class AccessService:
    @staticmethod
    def assign(profile_id, *, protocol_ids=None, admin):
        SecurityBarrier.assert_open(purpose="cloud_write")
        with transaction.atomic():
            profile = AccessProfile.objects.select_for_update().get(pk=profile_id)
            assert_entitled(profile)
            if protocol_ids is None:
                protocol_ids = list(
                    NodeProtocol.objects.filter(
                        enabled=True,
                        credential_scope="profile",
                        node__desired_state="PRESENT",
                        node__security_state="OPEN",
                    ).values_list("pk", flat=True)
                )
            protocols = list(
                NodeProtocol.objects.filter(
                    pk__in=protocol_ids,
                    enabled=True,
                    credential_scope="profile",
                    node__desired_state="PRESENT",
                    node__security_state="OPEN",
                ).select_related("node")
            )
            if len(protocols) != len(protocol_ids):
                raise DomainError(
                    "PROTOCOL_TARGET_MISMATCH", "所选协议不可分配或使用共享凭据", status_code=409
                )
            old = list(
                NodeCredential.objects.select_for_update().filter(
                    profile=profile, revoked_at__isnull=True
                )
            )
            old_ids = {c.protocol_id for c in old}
            changed_nodes = {c.node_id for c in old if c.protocol_id not in protocol_ids}
            for c in old:
                if c.protocol_id not in protocol_ids:
                    c.revoked_at = timezone.now()
                    c.save(update_fields=["revoked_at"])
            by_node = defaultdict(list)
            for p in protocols:
                if p.pk not in old_ids:
                    by_node[p.node_id].append(p.pk)
                    changed_nodes.add(p.node_id)
            # Lock all involved nodes in a consistent order.
            nodes = list(
                ManagedNode.objects.select_for_update().filter(pk__in=changed_nodes).order_by("pk")
            )
            for n in nodes:
                if n.pk in by_node:
                    CredentialService.rotate(
                        n.pk, profile_ids=[profile.pk], protocol_ids=by_node[n.pk]
                    )
                    n.refresh_from_db()
                else:
                    n.desired_generation = max(n.desired_generation, n.applied_generation) + 1
                    n.save(update_fields=["desired_generation", "updated_at"])
                # Every remaining credential is included in this full node config.
                NodeCredential.objects.filter(node=n, revoked_at__isnull=True).update(
                    desired_generation=n.desired_generation
                )
            if changed_nodes:
                SubscriptionRevision.objects.filter(
                    current_for_subscriptions__profile=profile, usable=True
                ).update(usable=False, invalidated_at=timezone.now())
            return [
                OperationService.submit(
                    kind="node.access_sync",
                    target_id=n.pk,
                    params={"generation": n.desired_generation},
                    key=uuid4(),
                    preview_id=None,
                    admin=admin,
                    cloud_credential_version=n.cloud_credential_version,
                )
                for n in nodes
            ]

    @staticmethod
    def sync(operation_id, *, transport_factory=None):
        operation = Operation.objects.get(pk=operation_id, kind="node.access_sync")
        if operation.status in Operation.TERMINAL_STATUSES:
            return
        claim = claim_operation(operation.pk, worker_id=f"access-sync-{uuid4()}", lease_seconds=90)
        try:
            SecurityBarrier.assert_open(purpose="cloud_write")
            factory = transport_factory or configured_factory()
            node = ManagedNode.objects.get(pk=operation.target_id)
            if node.desired_state != "PRESENT" or node.security_state != "OPEN":
                raise DomainError("NODE_NOT_OPEN", "节点不可下发", status_code=409)
            generation = operation.params["generation"]
            if generation != node.desired_generation:
                raise DomainError(
                    "STALE_CONFIG_GENERATION", "配置已被较新请求替代", status_code=409
                )
            assert_current(claim)
            config = build_node_config(node)
            result = NodeExecutor(transport_factory=factory).apply_config(
                node.pk, generation=generation, config=config, operation_id=operation.pk
            )
            assert_current(claim)
            NodeCredential.objects.filter(
                node=node, revoked_at__isnull=True, desired_generation=generation
            ).update(applied_generation=generation)
            ManagedNode.objects.filter(pk=node.pk).update(provisioning_state="READY")
            Operation.objects.filter(pk=operation.pk).update(
                result={"applied_generation": result.applied_generation}
            )
            release_claim(claim, status="SUCCEEDED")
        except Exception as exc:
            assert_current(claim)
            Operation.objects.filter(pk=operation.pk).update(
                error_code=getattr(exc, "code", "NODE_SYNC_FAILED"), error_details={}
            )
            release_claim(claim, status="FAILED")
            raise


def queue_policy_sync(profile):
    node_ids = NodeCredential.objects.filter(profile=profile, revoked_at__isnull=True).values_list(
        "node_id", flat=True
    )
    operations = []
    with transaction.atomic():
        for node in (
            ManagedNode.objects.select_for_update()
            .filter(pk__in=node_ids, desired_state="PRESENT", security_state="OPEN")
            .order_by("pk")
        ):
            node.desired_generation = max(node.desired_generation, node.applied_generation) + 1
            node.save(update_fields=["desired_generation", "updated_at"])
            NodeCredential.objects.filter(node=node, revoked_at__isnull=True).update(
                desired_generation=node.desired_generation
            )
            operations.append(
                OperationService.submit(
                    kind="node.access_sync",
                    target_id=node.pk,
                    params={"generation": node.desired_generation},
                    key=uuid4(),
                    preview_id=None,
                    cloud_credential_version=node.cloud_credential_version,
                )
            )
    return operations
