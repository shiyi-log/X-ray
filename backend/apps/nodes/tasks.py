from __future__ import annotations

from datetime import time, timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.identity.models import NodeAutomationSetting
from apps.operations.models import Operation
from apps.operations.services import ActionPreviewService, OperationService
from common.errors import DomainError
from common.regions import normalize_region


@shared_task
def schedule_node_status_refreshes():
    """Queue due read-only refreshes, leaving provider calls to the worker."""
    from apps.identity.models import NodeStatusSyncSetting, SuperAdmin
    from apps.nodes.models import ManagedNode
    from apps.operations.models import Operation
    from apps.operations.services import OperationService

    scheduled = 0
    skipped = 0
    with transaction.atomic():
        setting = (
            NodeStatusSyncSetting.objects.select_for_update()
            .filter(singleton_key=1)
            .first()
        )
        if setting is None or not setting.enabled:
            return {"scheduled": 0, "skipped": 0, "disabled": True}

        now = timezone.now()
        if setting.last_scheduled_at is not None:
            due_at = setting.last_scheduled_at + timedelta(minutes=setting.interval_minutes)
            if now < due_at:
                return {"scheduled": 0, "skipped": 0, "due_at": due_at.isoformat()}

        admin = SuperAdmin.objects.filter(singleton_key=1, is_active=True).first()
        if admin is None:
            return {"scheduled": 0, "skipped": 0, "admin_unavailable": True}

        nodes = (
            ManagedNode.objects.select_for_update()
            .filter(external_id__gt="")
            .exclude(desired_state="DELETED")
            .order_by("pk")
        )
        for node in nodes:
            in_flight = Operation.objects.filter(
                kind="node.refresh",
                target_id=node.pk,
            ).exclude(status__in=Operation.TERMINAL_STATUSES)
            if in_flight.exists():
                skipped += 1
                continue

            OperationService.submit(
                kind="node.refresh",
                target_id=node.pk,
                params={
                    "region": node.region,
                    "account_id": str(node.cloud_account_id),
                },
                key=uuid5(
                    NAMESPACE_URL,
                    f"xray-node-refresh:{setting.pk}:{node.pk}:{now.isoformat()}",
                ),
                preview_id=None,
                admin=admin,
                cloud_credential_version=node.cloud_credential_version,
            )
            scheduled += 1

        setting.last_scheduled_at = now
        setting.save(update_fields=["last_scheduled_at", "updated_at"])

    return {"scheduled": scheduled, "skipped": skipped, "at": now.isoformat()}


def _is_due(last_scheduled_at, interval_minutes: int, now) -> bool:
    return last_scheduled_at is None or now >= last_scheduled_at + timedelta(
        minutes=interval_minutes
    )


def _node_has_inflight_operation(node_id) -> bool:
    return Operation.objects.filter(target_type="node", target_id=node_id).exclude(
        status__in=Operation.TERMINAL_STATUSES
    ).exists()


@shared_task
def schedule_node_pool_sync():
    """Align quota-consuming node reservations with each desired regional quota."""
    from apps.cloud_accounts.models import CloudAccount
    from apps.identity.models import SuperAdmin
    from apps.nodes.models import ManagedNode, NodePool
    from apps.nodes.quota import ensure_pool_allocations, reserve_node

    created = deleted = skipped = blocked = 0
    with transaction.atomic():
        setting = (
            NodeAutomationSetting.objects.select_for_update()
            .filter(singleton_key=1)
            .first()
        )
        if setting is None or not setting.pool_sync_enabled:
            return {"created": 0, "deleted": 0, "skipped": 0, "disabled": True}

        now = timezone.now()
        if not _is_due(
            setting.pool_sync_last_scheduled_at,
            setting.pool_sync_interval_minutes,
            now,
        ):
            return {"created": 0, "deleted": 0, "skipped": 0, "due": False}

        pool = NodePool.objects.select_for_update().filter(singleton_key=1).first()
        admin = SuperAdmin.objects.filter(singleton_key=1, is_active=True).first()
        if pool is None or admin is None:
            return {
                "created": 0,
                "deleted": 0,
                "skipped": 0,
                "blocked": "POOL_OR_ADMIN_UNAVAILABLE",
            }

        allocations = ensure_pool_allocations(pool)
        templates = {
            normalize_region(item["region"]): item
            for item in setting.pool_sync_creation_templates
        }
        for allocation in sorted(allocations, key=lambda item: (item.region, str(item.pk))):
            allocation = type(allocation).objects.select_for_update().get(pk=allocation.pk)
            consuming = ManagedNode.objects.filter(
                pool=pool,
                region=allocation.region,
                consumes_quota=True,
            )
            used = consuming.count()
            if used < allocation.quota:
                deficit = allocation.quota - used
                template = templates.get(allocation.region)
                if not pool.allow_create or template is None:
                    blocked += deficit
                    continue
                try:
                    account = CloudAccount.objects.get(
                        pk=template["cloud_account_id"], enabled=True
                    )
                except CloudAccount.DoesNotExist:
                    blocked += deficit
                    continue
                for _ in range(deficit):
                    try:
                        with transaction.atomic():
                            node = reserve_node(
                                pool.pk,
                                account_id=account.pk,
                                region=allocation.region,
                                plan_id=template["plan_id"],
                                image_id=template["image_id"],
                                operation_key=uuid4(),
                            )
                            OperationService.submit(
                                kind="node.create",
                                target_id=node.pk,
                                params={
                                    "region": node.region,
                                    "account_id": str(node.cloud_account_id),
                                },
                                key=node.operation_key,
                                preview_id=None,
                                admin=admin,
                                cloud_credential_version=node.cloud_credential_version,
                            )
                    except DomainError:
                        blocked += 1
                        continue
                    created += 1
                continue

            excess = used - allocation.quota
            if not excess:
                continue
            oldest = (
                consuming.select_related("cloud_account", "cloud_credential_version")
                .order_by("created_at", "pk")
                .first()
            )
            from .automation import has_confirmed_instance_resource, node_delete_snapshot

            if oldest is None:
                blocked += excess
                continue
            if (
                not oldest.external_id
                or oldest.desired_state != "PRESENT"
                or oldest.provisioning_state != "READY"
                or oldest.security_state != "OPEN"
                or oldest.observation_error
                or not has_confirmed_instance_resource(oldest)
            ):
                blocked += 1
                continue
            if _node_has_inflight_operation(oldest.pk):
                skipped += 1
                continue
            params = {
                "region": oldest.region,
                "account_id": str(oldest.cloud_account_id),
                "confirmation": "确认删除服务器",
                "automation": {
                    "kind": "pool_sync",
                    "policy_version": setting.policy_version,
                }
            }
            preview = ActionPreviewService.create(
                admin=admin,
                kind="node.delete",
                target_id=oldest.pk,
                params=params,
                snapshot=node_delete_snapshot(oldest),
                required_phrase="确认删除服务器",
            )
            OperationService.submit(
                kind="node.delete",
                target_id=oldest.pk,
                params=params,
                key=uuid4(),
                preview_id=preview.pk,
                admin=admin,
                cloud_credential_version=oldest.cloud_credential_version,
            )
            deleted += 1

        setting.pool_sync_last_scheduled_at = now
        setting.save(update_fields=["pool_sync_last_scheduled_at", "updated_at"])

    return {
        "created": created,
        "deleted": deleted,
        "skipped": skipped,
        "blocked": blocked,
        "at": now.isoformat(),
    }


@shared_task
def schedule_daily_node_restart():
    """Queue at most one stable, eligible node restart per configured local day."""
    from apps.identity.models import SuperAdmin
    from apps.nodes.models import ManagedNode, NodeConfigRevision

    with transaction.atomic():
        setting = (
            NodeAutomationSetting.objects.select_for_update()
            .filter(singleton_key=1)
            .first()
        )
        if setting is None or not setting.daily_restart_enabled:
            return {"scheduled": 0, "disabled": True}
        now = timezone.now()
        try:
            zone = ZoneInfo(setting.daily_restart_timezone)
            scheduled_time = time.fromisoformat(setting.daily_restart_time)
        except (ValueError, ZoneInfoNotFoundError):
            return {"scheduled": 0, "invalid_schedule": True}
        if timezone.is_naive(now):
            return {"scheduled": 0, "invalid_clock": True}
        local_now = now.astimezone(zone)
        local_date = local_now.date()
        if local_now.timetz().replace(tzinfo=None) < scheduled_time:
            return {"scheduled": 0, "due": False}
        if setting.daily_restart_last_local_date == local_date:
            return {"scheduled": 0, "due": False, "local_date": local_date.isoformat()}

        inflight = Operation.objects.filter(
            kind="node.reboot",
            target_type="node",
            params__automation__kind="daily_restart",
        ).exclude(status__in=Operation.TERMINAL_STATUSES)
        if inflight.exists():
            return {"scheduled": 0, "in_flight": True}

        admin = SuperAdmin.objects.filter(singleton_key=1, is_active=True).first()
        if admin is None:
            return {"scheduled": 0, "admin_unavailable": True}
        nodes = list(
            ManagedNode.objects.select_for_update()
            .filter(
                external_id__gt="",
                provisioning_state="READY",
                desired_state="PRESENT",
                security_state="OPEN",
                raw_cloud_state__iexact="running",
                observation_error="",
            )
            .order_by("created_at", "pk")
        )
        if not nodes:
            return {"scheduled": 0, "no_eligible_nodes": True}

        from .probes import configured_health_probe

        if configured_health_probe() is None:
            return {"scheduled": 0, "blocked": "HEALTH_PROBE_UNAVAILABLE"}
        nodes = [
            candidate
            for candidate in nodes
            if candidate.desired_generation == candidate.applied_generation
            and NodeConfigRevision.objects.filter(
                node=candidate,
                generation=candidate.applied_generation,
                usable=True,
            ).exists()
        ]
        if not nodes:
            return {"scheduled": 0, "no_usable_configuration": True}

        previous_index = next(
            (
                index
                for index, node in enumerate(nodes)
                if node.pk == setting.daily_restart_last_node_id
            ),
            None,
        )
        if previous_index is not None:
            nodes = nodes[previous_index + 1 :] + nodes[: previous_index + 1]
        node = next(
            (
                candidate
                for candidate in nodes
                if not _node_has_inflight_operation(candidate.pk)
            ),
            None,
        )
        if node is None:
            return {"scheduled": 0, "no_idle_nodes": True}

        key = uuid5(NAMESPACE_URL, f"xray-daily-restart:{setting.pk}:{local_date.isoformat()}")
        operation = OperationService.submit(
            kind="node.reboot",
            target_id=node.pk,
            params={
                "region": node.region,
                "account_id": str(node.cloud_account_id),
                "automation": {
                    "kind": "daily_restart",
                    "policy_version": setting.policy_version,
                    "local_date": local_date.isoformat(),
                },
            },
            key=key,
            preview_id=None,
            admin=admin,
            cloud_credential_version=node.cloud_credential_version,
        )
        setting.daily_restart_last_local_date = local_date
        setting.daily_restart_last_node_id = node.pk
        setting.daily_restart_last_scheduled_at = now
        setting.save(
            update_fields=[
                "daily_restart_last_local_date",
                "daily_restart_last_node_id",
                "daily_restart_last_scheduled_at",
                "updated_at",
            ]
        )

    return {
        "scheduled": 1,
        "operation_id": str(operation.pk),
        "node_id": str(node.pk),
        "local_date": local_date.isoformat(),
        "at": now.isoformat(),
    }
