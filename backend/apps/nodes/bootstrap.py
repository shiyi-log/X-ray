from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone
from django.utils.module_loading import import_string

from apps.operations.claims import assert_current, claim_operation, release_claim
from apps.operations.models import Operation, OperationStep
from common.errors import DomainError

from .executor import NodeExecutor
from .models import ManagedNode, NodeProtocol

BOOTSTRAP_PROTOCOL = {
    "protocol": "shadowsocks",
    "listen_address": "0.0.0.0",
    "port": 8388,
    "network": "tcp",
    "transport": "tcp",
    "tls_enabled": False,
    "method": "aes-128-gcm",
    "credential_scope": "profile",
}
BOOTSTRAP_FIREWALL_RULES = (
    {"protocol": "tcp", "port": 8388},
    {"protocol": "udp", "port": 8388},
)
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def get_bootstrap_runtime():
    """Load the deployment adapter; local tests inject a Fake/Stub runtime."""
    path = getattr(settings, "XRAY_NODE_BOOTSTRAP_FACTORY", "")
    if not path:
        raise DomainError(
            "BOOTSTRAP_RUNTIME_UNAVAILABLE",
            "节点初始化运行时未配置",
            status_code=503,
        )
    try:
        runtime = import_string(path)()
    except Exception:
        raise DomainError(
            "BOOTSTRAP_RUNTIME_UNAVAILABLE",
            "节点初始化运行时不可用",
            status_code=503,
        ) from None
    required = ("install", "configure_firewall", "transport_factory", "health_probe")
    if any(not callable(getattr(runtime, name, None)) for name in required):
        raise DomainError(
            "BOOTSTRAP_RUNTIME_UNAVAILABLE",
            "节点初始化运行时接口不完整",
            status_code=503,
        )
    return runtime


def _pinned_manifest() -> dict:
    path = Path(__file__).resolve().parents[3] / "installer" / "manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise DomainError(
            "BOOTSTRAP_PINNED_MANIFEST_UNAVAILABLE",
            "固定版本安装清单不可用",
            status_code=503,
        ) from None
    if (
        value.get("schema_version") != 1
        or not isinstance(value.get("installer_version"), str)
        or not isinstance(value.get("xray_version"), str)
        or not isinstance(value.get("artifacts"), dict)
    ):
        raise DomainError(
            "BOOTSTRAP_PINNED_MANIFEST_INVALID",
            "固定版本安装清单无效",
            status_code=503,
        )
    return value


def _step(operation, *, name: str, status: str, evidence: dict) -> None:
    attempt = OperationStep.objects.filter(operation=operation, name=name).count() + 1
    now = timezone.now()
    OperationStep.objects.create(
        operation=operation,
        name=name,
        phase="bootstrap",
        status=status,
        attempt=attempt,
        evidence=evidence,
        started_at=now,
        finished_at=now,
    )


def _validate_installer_result(result, manifest: dict) -> dict:
    if not isinstance(result, dict):
        return {}
    platform = result.get("platform")
    artifact = manifest["artifacts"].get(platform)
    bundle_hash = result.get("bundle_hash")
    if (
        result.get("verified") is not True
        or artifact is None
        or result.get("installer_version") != manifest["installer_version"]
        or result.get("xray_version") != manifest["xray_version"]
        or not isinstance(bundle_hash, str)
        or not _SHA256_RE.fullmatch(bundle_hash)
        or bundle_hash != artifact.get("sha256")
    ):
        return {}
    return {
        "platform": platform,
        "installer_version": manifest["installer_version"],
        "xray_version": manifest["xray_version"],
        "bundle_hash": bundle_hash,
    }


def _verified_firewall_result(result) -> bool:
    return isinstance(result, dict) and all(
        result.get(field) is True
        for field in ("read_before_write", "write_confirmed", "read_after_write", "rules_verified")
    )


def _active_subscription_profile_ids() -> list[UUID]:
    from apps.subscriptions.models import Subscription, SubscriptionToken

    now = timezone.now()
    subscriptions = list(
        Subscription.objects.filter(
            status="ACTIVE",
            profile__status="ACTIVE",
            profile__publishing_frozen=False,
        )
        .filter(Q(profile__expires_at__isnull=True) | Q(profile__expires_at__gt=now))
        .values("id", "profile_id", "token_epoch", "token_digest")
    )
    if not subscriptions:
        return []
    active_ids = set(
        SubscriptionToken.objects.filter(
            subscription_id__in=[item["id"] for item in subscriptions],
            status="ACTIVE",
            token_epoch=F("subscription__token_epoch"),
            token_digest=F("subscription__token_digest"),
        ).values_list("subscription_id", flat=True)
    )
    return sorted(
        {item["profile_id"] for item in subscriptions if item["id"] in active_ids},
        key=str,
    )


def _ensure_protocol_and_generation(
    node_id, profile_ids: list[UUID]
) -> tuple[ManagedNode, NodeProtocol, int]:
    from apps.subscriptions.credentials import CredentialService
    from apps.subscriptions.models import NodeCredential

    try:
        with transaction.atomic():
            node = ManagedNode.objects.select_for_update().get(pk=node_id)
            protocol, _created = NodeProtocol.objects.get_or_create(
                node=node,
                protocol=BOOTSTRAP_PROTOCOL["protocol"],
                port=BOOTSTRAP_PROTOCOL["port"],
                network=BOOTSTRAP_PROTOCOL["network"],
                defaults={
                    key: value
                    for key, value in BOOTSTRAP_PROTOCOL.items()
                    if key not in {"protocol", "port", "network"}
                },
            )
            if (
                not protocol.enabled
                or protocol.listen_address != BOOTSTRAP_PROTOCOL["listen_address"]
                or protocol.transport != BOOTSTRAP_PROTOCOL["transport"]
                or protocol.tls_enabled
                or protocol.method != BOOTSTRAP_PROTOCOL["method"]
                or protocol.credential_scope != "profile"
            ):
                raise DomainError(
                    "BOOTSTRAP_PROTOCOL_UNAVAILABLE",
                    "节点初始化协议与固定模板不匹配",
                    status_code=409,
                )

            existing_profiles = set(
                NodeCredential.objects.filter(
                    node=node,
                    protocol=protocol,
                    revoked_at__isnull=True,
                    profile_id__in=profile_ids,
                ).values_list("profile_id", flat=True)
            )
            missing_profiles = [item for item in profile_ids if item not in existing_profiles]
            if missing_profiles:
                CredentialService.rotate(
                    node.pk,
                    profile_ids=missing_profiles,
                    protocol_ids=[protocol.pk],
                )
                node.refresh_from_db()
            else:
                node.desired_generation = max(node.desired_generation, node.applied_generation) + 1
                node.save(update_fields=["desired_generation", "updated_at"])
            generation = node.desired_generation
            NodeCredential.objects.filter(node=node, revoked_at__isnull=True).update(
                desired_generation=generation
            )
            return node, protocol, generation
    except IntegrityError:
        raise DomainError(
            "BOOTSTRAP_PROTOCOL_UNAVAILABLE",
            "固定初始化协议端口已被占用",
            status_code=409,
        ) from None


class NodeBootstrapService:
    """Install a pinned runtime, verify ingress, then publish only a healthy node."""

    @staticmethod
    def run(operation_id: UUID | str) -> None:
        operation = Operation.objects.get(pk=operation_id)
        if operation.status in Operation.TERMINAL_STATUSES:
            return
        claim = claim_operation(
            operation.pk,
            worker_id=f"node-bootstrap-{operation.pk}",
            lease_seconds=240,
        )
        preflight_complete = False
        try:
            operation = assert_current(claim)
            node = ManagedNode.objects.get(pk=operation.target_id)
            if (
                operation.kind != "node.bootstrap"
                or operation.target_type != "node"
                or node.cloud_credential_version_id != operation.cloud_credential_version_id
                or str(operation.params.get("region") or "") != node.region
                or str(operation.params.get("account_id") or "") != str(node.cloud_account_id)
            ):
                raise DomainError(
                    "OPERATION_TARGET_MISMATCH", "bootstrap 操作目标不匹配", status_code=409
                )
            if (
                node.desired_state != "PRESENT"
                or node.provisioning_state not in {"PROVISIONED", "RECONCILIATION", "READY"}
                or node.raw_cloud_state.casefold() != "running"
                or not node.external_id
            ):
                raise DomainError(
                    "NODE_NOT_BOOTSTRAPPABLE", "节点当前不能初始化", status_code=409
                )

            try:
                runtime = get_bootstrap_runtime()
            except DomainError as exc:
                _step(
                    operation,
                    name="bootstrap.preflight",
                    status="BLOCKED",
                    evidence={"error_code": exc.code},
                )
                raise
            preflight_complete = True
            _step(
                operation,
                name="bootstrap.preflight",
                status="SUCCEEDED",
                evidence={"node_state": node.provisioning_state, "runtime_available": True},
            )

            manifest = _pinned_manifest()
            try:
                installer_result = runtime.install(node, manifest)
            except DomainError as exc:
                _step(
                    operation,
                    name="bootstrap.installer",
                    status="FAILED",
                    evidence={"error_code": exc.code[:100]},
                )
                raise
            except Exception:
                _step(
                    operation,
                    name="bootstrap.installer",
                    status="FAILED",
                    evidence={"error_code": "BOOTSTRAP_INSTALLER_FAILED"},
                )
                raise DomainError(
                    "BOOTSTRAP_INSTALLER_FAILED", "固定版本安装未完成", status_code=409
                ) from None
            installer_evidence = _validate_installer_result(installer_result, manifest)
            if not installer_evidence:
                _step(
                    operation,
                    name="bootstrap.installer",
                    status="UNCONFIRMED",
                    evidence={"pinned_installer_verified": False},
                )
                raise DomainError(
                    "BOOTSTRAP_INSTALLER_UNVERIFIED", "固定版本安装结果无法验证", status_code=409
                )
            _step(
                operation,
                name="bootstrap.installer",
                status="SUCCEEDED",
                evidence={"pinned_installer_verified": True, **installer_evidence},
            )

            try:
                firewall_result = runtime.configure_firewall(node, BOOTSTRAP_FIREWALL_RULES)
            except DomainError as exc:
                _step(
                    operation,
                    name="bootstrap.firewall",
                    status="UNCONFIRMED",
                    evidence={"error_code": exc.code[:100]},
                )
                raise
            except Exception:
                _step(
                    operation,
                    name="bootstrap.firewall",
                    status="UNCONFIRMED",
                    evidence={"firewall_verified": False},
                )
                raise DomainError(
                    "BOOTSTRAP_FIREWALL_UNVERIFIED", "防火墙写入及回读未确认", status_code=409
                ) from None
            if not _verified_firewall_result(firewall_result):
                _step(
                    operation,
                    name="bootstrap.firewall",
                    status="UNCONFIRMED",
                    evidence={"firewall_verified": False},
                )
                raise DomainError(
                    "BOOTSTRAP_FIREWALL_UNVERIFIED", "防火墙写入及回读未确认", status_code=409
                )
            _step(
                operation,
                name="bootstrap.firewall",
                status="SUCCEEDED",
                evidence={"firewall_verified": True, "tcp_port": 8388, "udp_port": 8388},
            )

            profile_ids = _active_subscription_profile_ids()
            node, protocol, generation = _ensure_protocol_and_generation(node.pk, profile_ids)
            from apps.subscriptions.access import build_node_config
            from apps.subscriptions.models import NodeCredential

            config = build_node_config(node)
            try:
                apply_result = NodeExecutor(
                    transport_factory=runtime.transport_factory
                ).apply_config(
                    node.pk,
                    generation=generation,
                    config=config,
                    operation_id=operation.pk,
                )
            except DomainError as exc:
                _step(
                    operation,
                    name="bootstrap.config",
                    status="FAILED",
                    evidence={"error_code": exc.code[:100]},
                )
                raise
            except Exception:
                _step(
                    operation,
                    name="bootstrap.config",
                    status="FAILED",
                    evidence={"error_code": "BOOTSTRAP_CONFIG_APPLY_FAILED"},
                )
                raise DomainError(
                    "BOOTSTRAP_CONFIG_APPLY_FAILED", "节点配置应用未完成", status_code=409
                ) from None
            NodeCredential.objects.filter(
                node=node, revoked_at__isnull=True, desired_generation=generation
            ).update(applied_generation=generation)
            _step(
                operation,
                name="bootstrap.config",
                status="SUCCEEDED",
                evidence={
                    "generation": apply_result.applied_generation,
                    "config_test_passed": apply_result.config_test_passed,
                    "service_restarted": apply_result.service_restarted,
                },
            )

            ManagedNode.objects.filter(pk=node.pk).update(provisioning_state="PROVISIONED")
            node.refresh_from_db()
            from .probes import record_node_health_probe, run_node_health_probe

            probe_status, health_state, probe_evidence, health_generation = (
                run_node_health_probe(node, runtime.health_probe)
            )
            health_error = record_node_health_probe(
                node,
                external_id=node.external_id,
                generation=health_generation,
                health_state=health_state,
                probe_status=probe_status,
                probe_evidence=probe_evidence,
            )
            safe_probe_evidence = {
                field: probe_evidence.get(field)
                for field in ("accepted", "positive_control", "fresh_connection")
            }
            _step(
                operation,
                name="bootstrap.health",
                status="SUCCEEDED" if not health_error else "FAILED",
                evidence={"probe_status": probe_status, **safe_probe_evidence},
            )
            if health_error:
                raise DomainError(health_error, "节点健康探针未通过", status_code=409)

            ManagedNode.objects.filter(pk=node.pk).update(provisioning_state="READY")
            from apps.subscriptions.publishing import Publisher

            publication = Publisher.publish_for_node(node.pk)
            _step(
                operation,
                name="bootstrap.publish",
                status="SUCCEEDED" if publication["failed"] == 0 else "PARTIALLY_SUCCEEDED",
                evidence={
                    "published": publication["published"],
                    "failed": publication["failed"],
                },
            )
            if publication["failed"]:
                raise DomainError(
                    "BOOTSTRAP_SUBSCRIPTION_PUBLISH_FAILED",
                    "节点已健康但订阅发布未全部确认",
                    status_code=409,
                )
            Operation.objects.filter(pk=operation.pk).update(
                result={
                    "installer_version": installer_evidence["installer_version"],
                    "xray_version": installer_evidence["xray_version"],
                    "bundle_hash": installer_evidence["bundle_hash"],
                    "generation": generation,
                    "protocol": protocol.protocol,
                    "published_subscriptions": publication["published"],
                },
                error_code="",
                error_details={},
            )
            release_claim(claim, status="SUCCEEDED")
        except DomainError as exc:
            Operation.objects.filter(pk=operation.pk).update(
                error_code=exc.code,
                error_details={},
            )
            status = "NEEDS_RECONCILIATION" if preflight_complete or exc.code.startswith(
                "BOOTSTRAP_"
            ) else "FAILED"
            release_claim(
                claim,
                status=status,
            )
            return
        except Exception:
            Operation.objects.filter(pk=operation.pk).update(
                error_code="NODE_BOOTSTRAP_FAILED",
                error_details={},
            )
            release_claim(
                claim,
                status="NEEDS_RECONCILIATION" if preflight_complete else "FAILED",
            )
            raise
