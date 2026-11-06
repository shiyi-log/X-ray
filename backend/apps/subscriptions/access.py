from __future__ import annotations

from collections import defaultdict
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.module_loading import import_string

from apps.nodes.executor import NodeExecutor
from apps.nodes.models import ManagedNode, NodePoolRegionAllocation, NodeProtocol
from apps.operations.claims import assert_current, claim_operation, release_claim
from apps.operations.models import Operation
from apps.operations.services import OperationService
from common.errors import DomainError

from .credentials import CredentialService, decrypt_material
from .models import (
    AccessProfile,
    NodeCredential,
    Subscription,
    SubscriptionRevision,
    SubscriptionToken,
)
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
        claim = claim_operation(operation.pk, worker_id=f"access-sync-{uuid4()}", lease_seconds=240)
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
            ManagedNode.objects.filter(pk=node.pk).update(provisioning_state="PROVISIONED")
            node.refresh_from_db()
            from apps.nodes.probes import record_node_health_probe, run_node_health_probe

            probe_status, health_state, evidence, health_generation = run_node_health_probe(
                node
            )
            health_error = record_node_health_probe(
                node,
                external_id=node.external_id,
                generation=health_generation,
                health_state=health_state,
                probe_status=probe_status,
                probe_evidence=evidence,
            )
            result_data = {
                "applied_generation": result.applied_generation,
                "health_probe_status": probe_status,
                "health_state": health_state if not health_error else "UNKNOWN",
                "health_probe": evidence,
                "node_reconciliation": {"scheduled": 0, "operation_ids": []},
            }
            if health_error:
                Operation.objects.filter(pk=operation.pk).update(
                    result=result_data,
                    error_code=health_error,
                    error_details={},
                )
                release_claim(claim, status="NEEDS_RECONCILIATION")
                return

            ManagedNode.objects.filter(pk=node.pk).update(provisioning_state="READY")

            try:
                result_data["node_reconciliation"] = (
                    reconcile_node_for_active_subscriptions(node.pk)
                )
            except Exception:
                Operation.objects.filter(pk=operation.pk).update(
                    result=result_data,
                    error_code="NODE_SUBSCRIPTION_RECONCILIATION_FAILED",
                    error_details={},
                )
                release_claim(claim, status="NEEDS_RECONCILIATION")
                return

            from .publishing import Publisher, node_publish_ready

            node.refresh_from_db()
            if not result_data["node_reconciliation"]["operation_ids"] and node_publish_ready(node):
                Publisher.publish_for_node(node.pk)
            Operation.objects.filter(pk=operation.pk).update(
                result=result_data,
                error_code="",
                error_details={},
            )
            release_claim(claim, status="SUCCEEDED")
        except Exception as exc:
            assert_current(claim)
            Operation.objects.filter(pk=operation.pk).update(
                error_code=getattr(exc, "code", "NODE_SYNC_FAILED"), error_details={}
            )
            release_claim(claim, status="FAILED")
            raise


def reconcile_node_for_active_subscriptions(node_id):
    """Idempotently assign active subscriptions to a newly available node."""
    created_count = 0
    operation_ids = []
    with transaction.atomic():
        node = ManagedNode.objects.select_for_update().select_related("pool").get(pk=node_id)
        if (
            node.desired_state != "PRESENT"
            or node.provisioning_state != "READY"
            or node.raw_cloud_state.casefold() != "running"
            or node.security_state != "OPEN"
            or node.observation_error
            or node.desired_generation != node.applied_generation
        ):
            return {"scheduled": 0, "operation_ids": []}

        from .publishing import node_publish_ready

        if not node_publish_ready(node):
            return {"scheduled": 0, "operation_ids": []}

        # Honor the pool's regional allocation when present; legacy pools use region.
        allocation = NodePoolRegionAllocation.objects.filter(
            pool=node.pool, region=node.region
        ).first()
        if allocation is None and node.region != node.pool.region:
            return {"scheduled": 0, "operation_ids": []}
        if allocation is not None and allocation.quota == 0:
            return {"scheduled": 0, "operation_ids": []}

        protocols = list(
            NodeProtocol.objects.filter(
                node=node,
                enabled=True,
                credential_scope="profile",
            ).order_by("pk")
        )
        if not protocols:
            return {"scheduled": 0, "operation_ids": []}

        now = timezone.now()
        subscriptions = list(
            Subscription.objects.select_for_update()
            .select_related("profile")
            .filter(
                Q(profile__expires_at__isnull=True) | Q(profile__expires_at__gt=now),
                status="ACTIVE",
                profile__status="ACTIVE",
                profile__publishing_frozen=False,
            )
            .order_by("pk")
        )
        active_tokens = {
            (token.subscription_id, token.token_epoch, token.token_digest)
            for token in SubscriptionToken.objects.filter(
                subscription_id__in=[subscription.pk for subscription in subscriptions],
                status="ACTIVE",
            )
        }
        subscriptions = [
            subscription
            for subscription in subscriptions
            if (
                subscription.pk,
                subscription.token_epoch,
                subscription.token_digest,
            )
            in active_tokens
        ]

        existing = list(
            NodeCredential.objects.select_for_update()
            .filter(node=node, revoked_at__isnull=True)
            .select_related("node", "protocol")
            .order_by("profile_id", "protocol_id", "version")
        )
        existing_latest = {}
        for credential in existing:
            existing_latest[(credential.profile_id, credential.protocol_id)] = credential

        by_profile = {}
        for subscription in subscriptions:
            for protocol in protocols:
                key = (subscription.profile_id, protocol.pk)
                current = existing_latest.get(key)
                if current and current.credential_scope == "profile":
                    continue
                # Shared credentials must never be synthesized as per-profile entries.
                if protocol.credential_scope != "profile":
                    continue
                by_profile.setdefault(subscription.profile_id, []).append(protocol.pk)

        affected_nodes = set()
        for profile_id, protocol_ids in by_profile.items():
            CredentialService.rotate(
                node.pk,
                profile_ids=[profile_id],
                protocol_ids=protocol_ids,
            )
            created_count += len(protocol_ids)
            affected_nodes.add(node.pk)

        if affected_nodes:
            node.refresh_from_db()
            NodeCredential.objects.filter(node=node, revoked_at__isnull=True).update(
                desired_generation=node.desired_generation
            )
            operation = OperationService.submit(
                kind="node.access_sync",
                target_id=node.pk,
                params={"generation": node.desired_generation},
                key=uuid4(),
                preview_id=None,
                admin=None,
                cloud_credential_version=node.cloud_credential_version,
            )
            operation_ids.append(str(operation.pk))

    return {"scheduled": created_count, "operation_ids": operation_ids}


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
