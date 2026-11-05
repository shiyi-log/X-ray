from __future__ import annotations

import json
import os
import subprocess

from django.conf import settings
from django.db import transaction
from django.utils.module_loading import import_string

from .execution_types import ProbeResult
from .models import ManagedNode, NodeConfigRevision


def configured_health_probe():
    path = getattr(settings, "XRAY_NODE_HEALTH_PROBE", "")
    if not path:
        return None
    try:
        probe = import_string(path)
    except Exception:
        return None
    return probe if callable(probe) else None


def run_node_health_probe(node, health_probe=None):
    empty = {"accepted": None, "positive_control": None, "fresh_connection": None}
    try:
        candidate = ManagedNode.objects.select_related(
            "cloud_account", "cloud_credential_version"
        ).get(pk=node.pk)
    except Exception:
        return "UNAVAILABLE", "UNKNOWN", empty, node.applied_generation

    probe = health_probe if health_probe is not None else configured_health_probe()
    if probe is None:
        return "UNAVAILABLE", "UNKNOWN", empty, candidate.applied_generation
    try:
        result = probe(candidate)
        if isinstance(result, dict):
            values = {
                field: result.get(field)
                for field in ("accepted", "positive_control", "fresh_connection")
            }
        else:
            values = {
                field: getattr(result, field, None)
                for field in ("accepted", "positive_control", "fresh_connection")
            }
        evidence = {
            field: value if isinstance(value, bool) else None
            for field, value in values.items()
        }
    except Exception:
        return "FAILED", "UNHEALTHY", empty, candidate.applied_generation

    if all(value is True for value in evidence.values()):
        return "CONFIRMED", "HEALTHY", evidence, candidate.applied_generation
    return "FAILED", "UNHEALTHY", evidence, candidate.applied_generation


def record_node_health_probe(
    node,
    *,
    external_id: str,
    generation: int,
    health_state: str,
    probe_status: str,
    probe_evidence: dict[str, bool | None],
) -> str:
    with transaction.atomic():
        locked = ManagedNode.objects.select_for_update().get(pk=node.pk)
        if (
            locked.external_id != external_id
            or locked.desired_state != "PRESENT"
            or locked.applied_generation != generation
        ):
            locked.health_state = "UNKNOWN"
            locked.save(update_fields=["health_state", "updated_at"])
            NodeConfigRevision.objects.select_for_update().filter(
                node=locked, generation=locked.applied_generation
            ).update(probe_result={})
            return "NODE_CONFIG_GENERATION_CHANGED"

        revision = NodeConfigRevision.objects.select_for_update().filter(
            node=locked, generation=generation, usable=True
        ).first()
        if revision is None:
            locked.health_state = "UNKNOWN"
            locked.save(update_fields=["health_state", "updated_at"])
            NodeConfigRevision.objects.filter(node=locked, generation=generation).update(
                probe_result={}
            )
            return "NODE_CONFIG_REVISION_UNAVAILABLE"

        healthy = (
            probe_status == "CONFIRMED"
            and health_state == "HEALTHY"
            and all(
                probe_evidence.get(field) is True
                for field in ("accepted", "positive_control", "fresh_connection")
            )
        )
        if probe_status == "UNAVAILABLE":
            locked.health_state = "UNKNOWN"
            revision.probe_result = {}
            error_code = "NODE_HEALTH_PROBE_UNAVAILABLE"
        else:
            locked.health_state = "HEALTHY" if healthy else "UNHEALTHY"
            revision.probe_result = {
                "generation": generation,
                "app_health_passed": healthy,
                "accepted": probe_evidence.get("accepted"),
                "positive_control": probe_evidence.get("positive_control"),
                "fresh_connection": probe_evidence.get("fresh_connection"),
            }
            error_code = "" if healthy else "NODE_HEALTH_PROBE_FAILED"
        locked.save(update_fields=["health_state", "updated_at"])
        revision.save(update_fields=["probe_result"])
        return error_code


def curl_socks5h_probe(
    *,
    proxy_host: str,
    proxy_port: int,
    username: str,
    password: str,
    target_url: str,
    timeout: int = 10,
) -> ProbeResult:
    config = "\n".join(
        [
            'silent',
            'show-error',
            'fail',
            f'max-time = {int(timeout)}',
            f'proxy = "socks5h://{proxy_host}:{int(proxy_port)}"',
            f'proxy-user = "{username}:{password}"',
            f'url = "{target_url}"',
        ]
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if key.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    }
    completed = subprocess.run(
        ["curl", "--disable", "--config", "-"],
        input=config,
        text=True,
        capture_output=True,
        env=env,
        timeout=timeout + 2,
        check=False,
    )
    return ProbeResult(
        accepted=completed.returncode == 0,
        positive_control=True,
        fresh_connection=True,
        existing_session_closed=None,
        evidence={"exit_code": completed.returncode, "route": "socks5h"},
    )


def sanitized_probe_evidence(result: ProbeResult) -> str:
    return json.dumps(result.evidence, sort_keys=True, separators=(",", ":"))
