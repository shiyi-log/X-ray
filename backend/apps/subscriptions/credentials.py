from __future__ import annotations

import json
import secrets
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import Max

from apps.nodes.models import ManagedNode, NodeProtocol
from common.crypto import configured_subscription_store
from common.errors import DomainError

from .models import AccessProfile, NodeCredential


def _aad(credential_id: UUID, version: int) -> bytes:
    return f"credential:{credential_id}:{version}:material".encode()


def _new_material(protocol: NodeProtocol, profile: AccessProfile | None = None) -> dict:
    if protocol.protocol in {"vmess", "vless"}:
        return {"id": str(uuid4())}
    if protocol.protocol == "socks5":
        if profile is None:
            raise DomainError("PROFILE_REQUIRED", "SOCKS5 凭据需要访问身份", status_code=400)
        return {
            "username": f"p-{str(profile.pk)[:12]}",
            "password": secrets.token_urlsafe(24),
        }
    if protocol.protocol == "shadowsocks":
        return {
            "method": protocol.method or "aes-128-gcm",
            "password": secrets.token_urlsafe(24),
        }
    if protocol.protocol == "trojan":
        return {"password": secrets.token_urlsafe(32)}
    raise DomainError("PROTOCOL_UNSUPPORTED", "不支持的节点协议", status_code=400)


def decrypt_material(credential: NodeCredential) -> dict:
    payload = configured_subscription_store().decrypt(
        credential.encrypted_material,
        purpose="subscription.credential",
        aad=_aad(credential.pk, credential.version),
    )
    return json.loads(payload.decode("utf-8"))


class CredentialService:
    @staticmethod
    def rotate(
        node_id: UUID,
        *,
        profile_ids: list[UUID],
        protocol_ids: list[UUID],
    ) -> list[NodeCredential]:
        if not profile_ids or not protocol_ids:
            raise DomainError(
                "CREDENTIAL_TARGETS_REQUIRED", "必须选择身份和协议", status_code=400
            )
        with transaction.atomic():
            node = ManagedNode.objects.select_for_update().get(pk=node_id)
            protocols = list(
                NodeProtocol.objects.select_for_update()
                .filter(pk__in=protocol_ids, node=node, enabled=True)
                .order_by("pk")
            )
            if len(protocols) != len(set(protocol_ids)):
                raise DomainError(
                    "PROTOCOL_TARGET_MISMATCH", "协议不属于目标节点", status_code=409
                )
            requested = list(
                AccessProfile.objects.select_for_update()
                .filter(pk__in=profile_ids, status="ACTIVE")
                .order_by("pk")
            )
            if not requested:
                raise DomainError("PROFILE_NOT_ACTIVE", "没有活动访问身份", status_code=409)
            target_generation = max(node.desired_generation, node.applied_generation) + 1
            node.desired_generation = target_generation
            node.save(update_fields=["desired_generation", "updated_at"])
            created = []
            for protocol in protocols:
                if protocol.credential_scope == "shared":
                    profiles = list(
                        AccessProfile.objects.select_for_update()
                        .filter(status="ACTIVE")
                        .order_by("pk")
                    )
                    shared_material = _new_material(protocol)
                else:
                    profiles = requested
                    shared_material = None
                for profile in profiles:
                    latest = (
                        NodeCredential.objects.filter(
                            profile=profile, node=node, protocol=protocol
                        ).aggregate(value=Max("version"))["value"]
                        or 0
                    )
                    version = latest + 1
                    material = shared_material or _new_material(protocol, profile)
                    credential_id = uuid4()
                    envelope = configured_subscription_store().encrypt(
                        json.dumps(
                            material, sort_keys=True, separators=(",", ":")
                        ).encode(),
                        purpose="subscription.credential",
                        aad=_aad(credential_id, version),
                    )
                    created.append(
                        NodeCredential.objects.create(
                            id=credential_id,
                            profile=profile,
                            node=node,
                            protocol=protocol,
                            version=version,
                            encrypted_material=envelope,
                            credential_scope=protocol.credential_scope,
                            desired_generation=target_generation,
                            applied_generation=node.applied_generation,
                        )
                    )
            return created
