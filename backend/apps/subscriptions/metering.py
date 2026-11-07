from __future__ import annotations

import re
from collections import defaultdict
from uuid import UUID

from django.conf import settings
from django.utils.dateparse import parse_datetime
from django.utils.module_loading import import_string

from common.errors import DomainError

from .policy import UsageService

COUNTER = re.compile(r"^user>>>([^>]+)>>>traffic>>>(uplink|downlink)$")


def ambiguous_socks_profile_ids(node_ids):
    """Return profiles sharing an active SOCKS username prefix on a node."""
    from .models import NodeCredential

    aliases = defaultdict(set)
    credentials = (
        NodeCredential.objects.filter(
            node_id__in=node_ids,
            revoked_at__isnull=True,
            protocol__enabled=True,
            protocol__protocol="socks5",
            profile__status="ACTIVE",
        )
        .values_list("node_id", "profile_id")
        .distinct()
    )
    for node_id, profile_id in credentials:
        aliases[(node_id, str(profile_id)[:12])].add(str(profile_id))
    return {
        profile_id
        for profile_ids in aliases.values()
        if len(profile_ids) > 1
        for profile_id in profile_ids
    }


def _socks_profile_aliases(node):
    from .credentials import decrypt_material
    from .models import NodeCredential

    aliases = defaultdict(set)
    credentials = (
        NodeCredential.objects.filter(
            node=node,
            revoked_at__isnull=True,
            protocol__enabled=True,
            protocol__protocol="socks5",
            profile__status="ACTIVE",
        )
        .select_related("profile")
        .order_by("profile_id", "protocol_id", "version")
    )
    for credential in credentials:
        try:
            username = decrypt_material(credential).get("username")
        except Exception:
            raise ValueError("active SOCKS5 credential could not be read") from None
        if isinstance(username, str) and username:
            aliases[username].add(str(credential.profile_id))
    return {
        username: next(iter(profile_ids))
        for username, profile_ids in aliases.items()
        if len(profile_ids) == 1
    }


def _counter_profile_id(email, socks_aliases):
    if email.startswith("profile-"):
        try:
            return str(UUID(email[len("profile-") :]))
        except ValueError:
            return None
    return socks_aliases.get(email)


def ingest_snapshot(node, snapshot):
    """Input comes from a configured authenticated node fetcher, not a public API."""
    if snapshot.get("generation") != node.applied_generation:
        raise ValueError("usage generation mismatch")
    samples = defaultdict(lambda: [0, 0])
    seen = set()
    socks_aliases = _socks_profile_aliases(node)
    for item in snapshot.get("stat", []):
        match = COUNTER.fullmatch(item.get("name", ""))
        if not match:
            continue
        counter_name = item["name"]
        if counter_name in seen:
            raise ValueError("duplicate counter")
        seen.add(counter_name)
        identity = _counter_profile_id(match[1], socks_aliases)
        if identity is None:
            continue
        value = item.get("value", 0)
        if isinstance(value, str) and value.isdecimal():
            value = int(value)
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            or value > 2**63 - 1
        ):
            raise ValueError("invalid cumulative counter")
        direction = 0 if match[2] == "uplink" else 1
        total = samples[identity][direction] + value
        if total > 2**63 - 1:
            raise ValueError("invalid cumulative counter")
        samples[identity][direction] = total
    UsageService.record(
        node,
        epoch=f"{snapshot['boot_id']}:{snapshot['generation']}:{snapshot['process_id']}",
        sequence=snapshot["sequence"],
        samples=dict(samples),
        sampled_at=parse_datetime(snapshot["sampled_at"]),
    )
    return len(samples)


def collect_node(node, *, fetcher=None):
    if fetcher is None:
        path = getattr(settings, "XRAY_USAGE_FETCHER", "")
        if not path:
            raise DomainError(
                "USAGE_COLLECTOR_UNAVAILABLE", "尚未配置可信节点流量采集器", status_code=503
            )
        fetcher = import_string(path)
    return ingest_snapshot(node, fetcher(node))


def collect_node_once(node_id: UUID | str, *, fetcher=None):
    """Collect one explicitly selected ready node without applying global limits."""
    from apps.nodes.models import ManagedNode

    try:
        node_id = UUID(str(node_id))
    except (TypeError, ValueError) as exc:
        raise DomainError("NODE_ID_INVALID", "节点标识无效", status_code=400) from exc

    node = (
        ManagedNode.objects.select_related("cloud_account", "cloud_credential_version")
        .filter(pk=node_id)
        .first()
    )
    if node is None:
        raise DomainError("NODE_NOT_FOUND", "节点不存在", status_code=404)
    if (
        node.provisioning_state != "READY"
        or node.desired_state != "PRESENT"
        or node.security_state != "OPEN"
        or not node.external_id
    ):
        raise DomainError("NODE_NOT_COLLECTABLE", "节点当前不可采集流量", status_code=409)
    return collect_node(node, fetcher=fetcher)
