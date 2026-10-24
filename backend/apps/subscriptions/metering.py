from __future__ import annotations

import re
from collections import defaultdict
from uuid import UUID

from common.errors import DomainError
from django.conf import settings
from django.utils.dateparse import parse_datetime
from django.utils.module_loading import import_string

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
