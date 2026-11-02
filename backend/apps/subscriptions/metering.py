from __future__ import annotations

import re
from collections import defaultdict
from uuid import UUID

from django.conf import settings
from django.utils.dateparse import parse_datetime
from django.utils.module_loading import import_string

from common.errors import DomainError

from .policy import UsageService

COUNTER = re.compile(r"^user>>>profile-([0-9a-f-]{36})>>>traffic>>>(uplink|downlink)$")


def ingest_snapshot(node, snapshot):
    """Input comes from a configured authenticated node fetcher, not a public API."""
    if snapshot.get("generation") != node.applied_generation:
        raise ValueError("usage generation mismatch")
    samples = defaultdict(lambda: [0, 0])
    seen = set()
    for item in snapshot.get("stat", []):
        match = COUNTER.fullmatch(item.get("name", ""))
        if not match:
            continue
        identity = str(UUID(match[1]))
        key = (identity, match[2])
        if key in seen:
            raise ValueError("duplicate counter")
        seen.add(key)
        value = item.get("value", 0)
        if isinstance(value, str) and value.isdecimal():
            value = int(value)
        samples[identity][0 if match[2] == "uplink" else 1] = value
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
