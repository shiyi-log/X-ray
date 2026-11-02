from __future__ import annotations

from uuid import uuid4

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.nodes.models import ManagedNode
from apps.operations.services import OperationService

from .models import AccessProfile, NodeCredential
from .policy import quota_state


def enforce_limits():
    operations = []
    with transaction.atomic():
        blocked = [
            p.pk
            for p in AccessProfile.objects.select_for_update().filter(status="ACTIVE")
            if quota_state(p) != "ACTIVE"
        ]
        node_ids = NodeCredential.objects.filter(
            profile_id__in=blocked, revoked_at__isnull=True
        ).values_list("node_id", flat=True)
        nodes = (
            ManagedNode.objects.select_for_update()
            .filter(pk__in=node_ids, desired_state="PRESENT", security_state="OPEN")
            .order_by("pk")
        )
        for node in nodes:
            # One queued application per generation. Public reads are already denied.
            if node.desired_generation != node.applied_generation:
                continue
            from apps.nodes.executor import _config_hash

            from .access import build_node_config

            if node.applied_config_hash == _config_hash(build_node_config(node)):
                continue
            node.desired_generation += 1
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


@shared_task
def refresh_usage_and_limits():
    from .metering import collect_node

    result = {"collected": 0, "unavailable": 0}
    for node in ManagedNode.objects.filter(
        provisioning_state="READY", desired_state="PRESENT", security_state="OPEN"
    ):
        try:
            collect_node(node)
            result["collected"] += 1
        except Exception:
            result["unavailable"] += 1
    result["enforcement_operations"] = len(enforce_limits())
    result["at"] = timezone.now().isoformat()
    return result
