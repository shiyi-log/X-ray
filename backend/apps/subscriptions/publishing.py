from __future__ import annotations

import hashlib
import ipaddress
import secrets
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from common.crypto import configured_subscription_store
from common.errors import DomainError

from .credentials import decrypt_material
from .models import (
    AccessProfile,
    NodeCredential,
    PublicationBatch,
    RevocationTombstone,
    Subscription,
    SubscriptionRevision,
    SubscriptionToken,
)
from .policy import assert_entitled
from .renderers import NoCompatibleEndpoints, render_subscription
from .security_barrier import SecurityBarrier


def _usable_addresses(node) -> list[tuple[int, str]]:
    """Return deduplicated addresses whose declared family matches the IP value."""
    addresses = node.addresses if isinstance(node.addresses, list) else []
    usable = []
    seen_hosts = set()
    for item in addresses:
        if not isinstance(item, dict) or not item.get("value"):
            continue
        host = str(item["value"])
        try:
            address = ipaddress.ip_address(host)
            family = int(item.get("family") or address.version)
        except (TypeError, ValueError):
            continue
        if family != address.version or family not in {4, 6} or host in seen_hosts:
            continue
        seen_hosts.add(host)
        usable.append((family, host))
    return usable


def node_publish_ready(node, *, allow_bootstrapping: bool = False) -> bool:
    """Return whether a node has current, independently verified publish evidence."""
    allowed_states = {"READY"}
    if allow_bootstrapping:
        allowed_states.update({"PROVISIONED", "RECONCILIATION"})
    if (
        node.raw_cloud_state.casefold() != "running"
        or node.desired_state != "PRESENT"
        or node.provisioning_state not in allowed_states
        or node.health_state != "HEALTHY"
        or node.security_state != "OPEN"
        or node.observation_error
        or node.desired_generation != node.applied_generation
        or not _usable_addresses(node)
    ):
        return False
    from apps.nodes.models import NodeConfigRevision

    revision = (
        NodeConfigRevision.objects.filter(
            node=node,
            generation=node.applied_generation,
            usable=True,
        )
        .order_by("-created_at")
        .first()
    )
    if revision is None:
        return False
    probe = revision.probe_result if isinstance(revision.probe_result, dict) else {}
    return (
        probe.get("generation") == node.applied_generation
        and probe.get("app_health_passed") is True
        and probe.get("accepted") is True
        and probe.get("positive_control") is True
        and probe.get("fresh_connection") is True
    )


def credential_publish_ready(credential, *, allow_bootstrapping: bool = False) -> bool:
    node = credential.node
    protocol = credential.protocol
    return (
        node_publish_ready(node, allow_bootstrapping=allow_bootstrapping)
        and node.security_state == "OPEN"
        and node.desired_generation == node.applied_generation
        and credential.desired_generation == credential.applied_generation
        and credential.applied_generation == node.applied_generation
        and credential.revoked_at is None
        and protocol.enabled
        and protocol.credential_scope == "profile"
        and (
            protocol.protocol != "trojan"
            or (protocol.tls_enabled and bool(protocol.server_name))
        )
    )

FORMATS = ("shadowrocket", "clash", "mihomo", "v2ray")


class NoPublishableEndpoints(DomainError):
    def __init__(self):
        super().__init__("NO_PUBLISHABLE_ENDPOINTS", "没有已验证可发布的节点", status_code=422)


def _payload_aad(revision: SubscriptionRevision, format: str) -> bytes:
    return f"revision:{revision.pk}:{revision.number}:{format}".encode()


def decrypt_payload(revision: SubscriptionRevision, format: str) -> bytes:
    return configured_subscription_store().decrypt(
        revision.payloads[format],
        purpose="subscription.payload",
        aad=_payload_aad(revision, format),
    )


class Publisher:
    @staticmethod
    def _has_confirmed_current_token_revocation(subscription: Subscription) -> bool:
        token = SubscriptionToken.objects.filter(
            subscription=subscription,
            token_epoch=subscription.token_epoch,
            token_digest=subscription.token_digest,
        ).first()
        if (
            token is None
            or token.status != "REVOKED"
            or token.revoked_at is None
            or SubscriptionToken.objects.filter(
                subscription=subscription, status="ACTIVE"
            ).exists()
        ):
            return False
        return RevocationTombstone.objects.filter(
            token_digest=token.token_digest,
            revoked_at=token.revoked_at,
            source_event_id__gt="",
            source_sequence__isnull=False,
        ).exists()

    @staticmethod
    def _endpoints(
        subscription: Subscription,
        *,
        excluded_node_ids: set[UUID],
        allow_bootstrapping: bool = False,
    ) -> list[dict]:
        credentials = list(
            NodeCredential.objects.select_for_update()
            .select_related("node", "protocol", "profile")
            .filter(profile=subscription.profile, revoked_at__isnull=True)
            .order_by("node_id", "protocol_id", "version")
        )
        latest = {}
        for credential in credentials:
            latest[(credential.node_id, credential.protocol_id)] = credential
        endpoints = []
        for credential in latest.values():
            node = credential.node
            protocol = credential.protocol
            if node.pk in excluded_node_ids:
                continue
            if not credential_publish_ready(
                credential, allow_bootstrapping=allow_bootstrapping
            ):
                continue
            for family, host in _usable_addresses(node):
                endpoints.append(
                    {
                        "node_id": str(node.pk),
                        "name": (
                            f"{subscription.profile.name}-{str(node.pk)[:8]}-"
                            f"{protocol.protocol}-v{family}"
                        ),
                        "protocol": protocol.protocol,
                        "host": host,
                        "port": protocol.port,
                        "transport": protocol.transport,
                        "tls": protocol.tls_enabled,
                        "server_name": protocol.server_name,
                        "allow_insecure": False,
                        "credential_ref": str(credential.pk),
                        "credential_version": credential.version,
                        "address_family": family,
                        "applied_generation": credential.applied_generation,
                        "credential": decrypt_material(credential),
                    }
                )
        return endpoints

    @classmethod
    def _publish_locked(
        cls,
        subscription: Subscription,
        *,
        excluded_node_ids: set[UUID] | None = None,
        allow_bootstrapping: bool = False,
    ) -> SubscriptionRevision:
        if (
            subscription.status != "ACTIVE"
            or subscription.profile.status != "ACTIVE"
            or subscription.profile.publishing_frozen
        ):
            raise DomainError("SUBSCRIPTION_PUBLISHING_FROZEN", "订阅发布已冻结", status_code=409)
        if not SubscriptionToken.objects.filter(
            subscription=subscription,
            token_epoch=subscription.token_epoch,
            token_digest=subscription.token_digest,
            status="ACTIVE",
        ).exists():
            raise DomainError(
                "SUBSCRIPTION_TOKEN_INACTIVE", "订阅令牌不是活动状态", status_code=409
            )
        assert_entitled(subscription.profile)
        endpoints = cls._endpoints(
            subscription,
            excluded_node_ids=excluded_node_ids or set(),
            allow_bootstrapping=allow_bootstrapping,
        )
        if not endpoints:
            raise NoPublishableEndpoints()
        number = (
            subscription.revisions.order_by("-number").values_list("number", flat=True).first() or 0
        ) + 1
        revision = SubscriptionRevision(
            id=uuid4(),
            subscription=subscription,
            number=number,
            public_version=secrets.token_urlsafe(16),
            node_versions={},
        )
        payloads = {}
        payload_hashes = {}
        unavailable = {}
        for format in FORMATS:
            try:
                body = render_subscription(
                    format, endpoints=endpoints, public_version=revision.public_version
                )
            except NoCompatibleEndpoints as exc:
                unavailable[format] = exc.code
                continue
            payloads[format] = configured_subscription_store().encrypt(
                body,
                purpose="subscription.payload",
                aad=_payload_aad(revision, format),
            )
            payload_hashes[format] = hashlib.sha256(body).hexdigest()
        if not payloads:
            raise NoPublishableEndpoints()
        revision.payloads = payloads
        revision.payload_hashes = payload_hashes
        revision.unavailable_reasons = unavailable
        revision.node_versions = {
            f'{endpoint["node_id"]}:{endpoint["credential_ref"]}:v{endpoint["address_family"]}': {
                "node_id": endpoint["node_id"],
                "applied_generation": endpoint["applied_generation"],
                "credential_ref": endpoint["credential_ref"],
                "credential_version": endpoint["credential_version"],
                "address_family": endpoint["address_family"],
                "host": endpoint["host"],
            }
            for endpoint in endpoints
        }
        revision.save(force_insert=True)
        if subscription.current_revision_id:
            SubscriptionRevision.objects.filter(
                pk=subscription.current_revision_id, usable=True
            ).update(usable=False, invalidated_at=timezone.now())
        subscription.current_revision = revision
        subscription.save(update_fields=["current_revision", "updated_at"])
        return revision

    @classmethod
    def publish(cls, subscription_id: UUID) -> SubscriptionRevision:
        SecurityBarrier.assert_open(purpose="public_read")
        with transaction.atomic():
            subscription = Subscription.objects.select_for_update().get(pk=subscription_id)
            subscription.profile = AccessProfile.objects.select_for_update().get(
                pk=subscription.profile_id
            )
            return cls._publish_locked(subscription)

    @classmethod
    def refresh_node_address(cls, node_id: UUID) -> dict[str, int]:
        """Republish affected subscriptions and fail closed on stale node addresses."""
        with transaction.atomic():
            subscriptions = list(
                Subscription.objects.select_for_update()
                .filter(status="ACTIVE")
                .order_by("pk")
            )
            profiles = {
                profile.pk: profile
                for profile in AccessProfile.objects.select_for_update()
                .filter(
                    pk__in=[value.profile_id for value in subscriptions],
                    status="ACTIVE",
                )
                .order_by("pk")
            }
            affected = []
            node_id_text = str(node_id)
            for subscription in subscriptions:
                if subscription.profile_id not in profiles:
                    continue
                subscription.profile = profiles[subscription.profile_id]
                revision = subscription.current_revision
                if revision is None:
                    continue
                if any(
                    key == node_id_text or value.get("node_id") == node_id_text
                    for key, value in revision.node_versions.items()
                ):
                    affected.append(subscription)

            SubscriptionRevision.objects.filter(
                pk__in=[value.current_revision_id for value in affected], usable=True
            ).update(usable=False, invalidated_at=timezone.now())

            published = 0
            failed = 0
            for subscription in affected:
                try:
                    with transaction.atomic():
                        SecurityBarrier.assert_open(purpose="public_read")
                        cls._publish_locked(subscription)
                    published += 1
                except Exception as exc:
                    if (
                        isinstance(exc, DomainError)
                        and exc.code == "SUBSCRIPTION_TOKEN_INACTIVE"
                        and cls._has_confirmed_current_token_revocation(subscription)
                    ):
                        continue
                    failed += 1
            return {"published": published, "failed": failed}

    @classmethod
    def invalidate_node(cls, node_id: UUID) -> PublicationBatch:
        with transaction.atomic():
            subscriptions = list(
                Subscription.objects.select_for_update().filter(status="ACTIVE").order_by("pk")
            )
            profiles = {
                profile.pk: profile
                for profile in AccessProfile.objects.select_for_update()
                .filter(
                    pk__in=[value.profile_id for value in subscriptions],
                    status="ACTIVE",
                )
                .order_by("pk")
            }
            subscriptions = [
                subscription
                for subscription in subscriptions
                if subscription.profile_id in profiles
            ]
            for subscription in subscriptions:
                subscription.profile = profiles[subscription.profile_id]
            affected = [
                subscription
                for subscription in subscriptions
                if subscription.current_revision_id
                and any(
                    key == str(node_id) or value.get("node_id") == str(node_id)
                    for key, value in subscription.current_revision.node_versions.items()
                )
            ]
            batch = PublicationBatch.objects.create(
                excluded_node_id=node_id,
                subscription_ids=[str(value.pk) for value in affected],
            )
            SubscriptionRevision.objects.filter(
                pk__in=[value.current_revision_id for value in affected]
            ).update(usable=False, invalidated_at=timezone.now())
            completed = 0
            skipped = 0
            failures = []
            for subscription in affected:
                try:
                    cls._publish_locked(subscription, excluded_node_ids={node_id})
                    completed += 1
                except (NoPublishableEndpoints, DomainError) as exc:
                    if (
                        isinstance(exc, DomainError)
                        and exc.code == "SUBSCRIPTION_TOKEN_INACTIVE"
                        and cls._has_confirmed_current_token_revocation(subscription)
                    ):
                        skipped += 1
                        continue
                    failures.append({"subscription_id": str(subscription.pk), "code": exc.code})
            batch.status = "SUCCEEDED" if not failures else "PARTIALLY_SUCCEEDED"
            batch.result = {"published": completed, "skipped": skipped, "failures": failures}
            batch.completed_at = timezone.now()
            batch.save(update_fields=["status", "result", "completed_at"])
            return batch

    @classmethod
    def publish_for_node(
        cls,
        node_id: UUID,
        *,
        allow_bootstrapping: bool = False,
        require_all: bool = False,
    ) -> dict[str, int]:
        """Publish active subscriptions assigned to a node after access sync."""
        from apps.nodes.models import ManagedNode

        class _RequiredPublicationFailure(Exception):
            pass

        failed = 0
        try:
            with transaction.atomic():
                node = ManagedNode.objects.select_for_update().get(pk=node_id)
                if not node_publish_ready(node, allow_bootstrapping=allow_bootstrapping):
                    if require_all:
                        raise DomainError(
                            "NODE_NOT_READY_FOR_PUBLICATION",
                            "节点当前不满足订阅发布条件",
                            status_code=409,
                        )
                    return {"published": 0, "failed": 0}
                node_credential = NodeCredential.objects.filter(
                    profile_id=OuterRef("profile_id"),
                    node_id=node_id,
                    revoked_at__isnull=True,
                )
                subscriptions = list(
                    Subscription.objects.select_for_update()
                    .filter(
                        status="ACTIVE",
                        profile__status="ACTIVE",
                        profile__publishing_frozen=False,
                    )
                    .filter(Exists(node_credential))
                    .order_by("pk")
                )
                profiles = {
                    profile.pk: profile
                    for profile in AccessProfile.objects.select_for_update().filter(
                        pk__in=[subscription.profile_id for subscription in subscriptions]
                    )
                }
                published = 0
                for subscription in subscriptions:
                    subscription.profile = profiles[subscription.profile_id]
                    try:
                        cls._publish_locked(
                            subscription,
                            allow_bootstrapping=allow_bootstrapping,
                        )
                        published += 1
                    except Exception:
                        failed += 1
                        if require_all:
                            failed = len(subscriptions) - published
                            raise _RequiredPublicationFailure from None
                return {"published": published, "failed": failed}
        except _RequiredPublicationFailure:
            return {"published": 0, "failed": failed}
