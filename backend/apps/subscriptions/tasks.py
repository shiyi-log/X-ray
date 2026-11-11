from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.identity.models import NodeAutomationSetting
from apps.nodes.models import ManagedNode
from apps.operations.services import OperationService

from .models import AccessProfile, NodeCredential
from .policy import quota_state

USAGE_SYNC_LEASE_MINUTES = 5


def _claim_usage_sync_node(node_id, now, *, retry_only):
    lease_id = uuid4()
    eligible = ManagedNode.objects.filter(
        pk=node_id,
        provisioning_state="READY",
        desired_state="PRESENT",
        security_state="OPEN",
        external_id__gt="",
    ).filter(Q(usage_sync_lease_id__isnull=True) | Q(usage_sync_lease_expires_at__lte=now))
    if retry_only:
        eligible = eligible.filter(
            Q(usage_sync_retry_at__lte=now)
            | Q(usage_sync_lease_id__isnull=False, usage_sync_lease_expires_at__lte=now)
        )
    claimed = eligible.update(
        usage_sync_lease_id=lease_id,
        usage_sync_lease_expires_at=now + timedelta(minutes=USAGE_SYNC_LEASE_MINUTES),
    )
    if not claimed:
        return None
    node = (
        ManagedNode.objects.select_related("cloud_account", "cloud_credential_version")
        .get(pk=node_id, usage_sync_lease_id=lease_id)
    )
    return lease_id, node


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

    now = timezone.now()
    setting, _created = NodeAutomationSetting.objects.get_or_create(singleton_key=1)
    with transaction.atomic():
        setting = NodeAutomationSetting.objects.select_for_update().get(pk=setting.pk)
        due = setting.usage_sync_enabled and (
            setting.usage_sync_last_scheduled_at is None
            or now
            >= setting.usage_sync_last_scheduled_at
            + timedelta(minutes=setting.usage_sync_interval_minutes)
        )
        if due:
            setting.usage_sync_last_scheduled_at = now
            setting.save(update_fields=["usage_sync_last_scheduled_at", "updated_at"])

    result = {"collected": 0, "unavailable": 0}
    retry_only = not due
    if due:
        eligible = ManagedNode.objects.filter(
            provisioning_state="READY",
            desired_state="PRESENT",
            security_state="OPEN",
            external_id__gt="",
        ).order_by("pk")
        nodes = list(eligible)
        due_node_ids = {node.pk for node in nodes}
    else:
        due_node_ids = set(
            ManagedNode.objects.filter(
                Q(usage_sync_retry_at__lte=now)
                | Q(usage_sync_lease_id__isnull=False, usage_sync_lease_expires_at__lte=now),
                provisioning_state="READY",
                desired_state="PRESENT",
                security_state="OPEN",
                external_id__gt="",
            ).values_list("pk", flat=True)
        )
        nodes = list(
            ManagedNode.objects.filter(pk__in=due_node_ids).order_by("pk")
        )
    if setting.usage_sync_enabled and (due or due_node_ids):
        for candidate in nodes:
            claimed_at = timezone.now()
            claim = _claim_usage_sync_node(
                candidate.pk, claimed_at, retry_only=retry_only
            )
            if claim is None:
                continue
            lease_id, node = claim
            try:
                collect_node(node)
                result["collected"] += 1
                ManagedNode.objects.filter(pk=node.pk, usage_sync_lease_id=lease_id).update(
                    usage_sync_retry_count=0,
                    usage_sync_retry_at=None,
                    usage_sync_lease_id=None,
                    usage_sync_lease_expires_at=None,
                )
            except Exception:
                result["unavailable"] += 1
                retry_count = min(node.usage_sync_retry_count + 1, 7)
                retry_minutes = min(2 ** (retry_count - 1), 60)
                retry_at = timezone.now() + timedelta(minutes=retry_minutes)
                ManagedNode.objects.filter(pk=node.pk, usage_sync_lease_id=lease_id).update(
                    usage_sync_retry_count=retry_count,
                    usage_sync_retry_at=retry_at,
                    usage_sync_lease_id=None,
                    usage_sync_lease_expires_at=None,
                )
    result["enforcement_operations"] = len(enforce_limits())
    result["at"] = now.isoformat()
    return result
