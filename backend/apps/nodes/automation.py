from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.utils import timezone

from apps.identity.models import NodeAutomationSetting
from apps.operations.models import Operation
from apps.operations.services import canonical_hash, preview_params
from common.errors import DomainError

from .models import ManagedNode, NodePool, NodeResource


def node_delete_snapshot(node: ManagedNode) -> dict:
    return {
        "external_id": node.external_id,
        "region": node.region,
        "account_id": str(node.cloud_account_id),
        "addresses": list(node.addresses or []),
        "desired_state": node.desired_state,
        "desired_generation": node.desired_generation,
    }


def has_confirmed_instance_resource(node: ManagedNode) -> bool:
    return NodeResource.objects.filter(
        node=node,
        kind="instance",
        external_id=node.external_id,
        ownership_tags__contains={
            "xray-manager": "true",
            "xray-node": str(node.pk),
            "xray-operation": str(node.operation_key),
        },
        cost_status="ACTIVE",
    ).exists()


@transaction.atomic
def has_subscription_endpoint_fallback(node: ManagedNode) -> bool:
    """Require affected active subscriptions to retain a publishable endpoint."""
    from apps.subscriptions.models import Subscription
    from apps.subscriptions.publishing import Publisher
    from apps.subscriptions.renderers import NoCompatibleEndpoints, render_subscription

    node_id = str(node.pk)
    subscriptions = (
        Subscription.objects.select_for_update(of=("self",))
        .select_related("profile", "current_revision")
        .filter(status="ACTIVE", profile__status="ACTIVE")
        .order_by("pk")
    )
    for subscription in subscriptions:
        revision = subscription.current_revision
        node_versions = revision.node_versions if revision else {}
        if not isinstance(node_versions, dict) or not any(
            key == node_id
            or (isinstance(value, dict) and value.get("node_id") == node_id)
            for key, value in node_versions.items()
        ):
            continue
        required_formats = revision.payloads if revision else {}
        if not isinstance(required_formats, dict) or not required_formats:
            return False
        try:
            endpoints = Publisher._endpoints(subscription, excluded_node_ids={node.pk})
            if not endpoints:
                return False
            for subscription_format in required_formats:
                try:
                    render_subscription(
                        subscription_format,
                        endpoints=endpoints,
                        public_version="fallback-check",
                    )
                except NoCompatibleEndpoints:
                    return False
        except Exception:
            return False
    return True


@transaction.atomic
def validate_automated_delete(
    operation: Operation, node: ManagedNode, policy_version: int
) -> None:
    """Fence queued pool deletions against the current desired quota and target."""
    automation = operation.params.get("automation")
    if (
        operation.kind != "node.delete"
        or operation.target_type != "node"
        or operation.target_id != node.pk
        or not isinstance(automation, dict)
        or automation.get("kind") != "pool_sync"
        or isinstance(policy_version, bool)
        or not isinstance(policy_version, int)
        or automation.get("policy_version") != policy_version
    ):
        raise DomainError("AUTOMATION_POLICY_STALE", "自动删除策略已变化", status_code=409)

    setting = NodeAutomationSetting.objects.select_for_update().filter(singleton_key=1).first()
    if (
        setting is None
        or not setting.pool_sync_enabled
        or setting.policy_version != policy_version
    ):
        raise DomainError("AUTOMATION_POLICY_STALE", "自动删除策略已变化", status_code=409)

    pool = NodePool.objects.select_for_update().filter(singleton_key=1).first()
    node = ManagedNode.objects.select_for_update().select_related(
        "cloud_account", "cloud_credential_version"
    ).get(pk=node.pk)
    if pool is None or node.pool_id != pool.pk:
        raise DomainError("AUTOMATION_TARGET_INELIGIBLE", "自动删除目标已变化", status_code=409)
    allocation = pool.region_allocations.select_for_update().filter(region=node.region).first()
    if allocation is None:
        raise DomainError("AUTOMATION_OVERAGE_CHANGED", "地区额度已变化", status_code=409)

    preview = operation.preview
    now = timezone.now()
    if (
        preview is None
        or preview.kind != "node.delete"
        or preview.target_id != node.pk
        or preview.consumed_at is None
        or preview.expires_at <= now
        or preview.required_phrase != operation.params.get("confirmation")
        or preview.params_hash != canonical_hash(preview_params(operation.params))
        or preview.snapshot != node_delete_snapshot(node)
        or operation.params.get("region") != node.region
        or operation.params.get("account_id") != str(node.cloud_account_id)
    ):
        raise DomainError("AUTOMATION_PREVIEW_STALE", "自动删除预览已失效", status_code=409)

    if (
        node.external_id == ""
        or node.desired_state != "PRESENT"
        or node.provisioning_state != "READY"
        or node.security_state != "OPEN"
        or node.observation_error
        or not has_confirmed_instance_resource(node)
    ):
        raise DomainError(
            "AUTOMATION_TARGET_INELIGIBLE", "自动删除目标缺少有效资源读回", status_code=409
        )

    consuming = ManagedNode.objects.filter(
        pool=pool, region=node.region, consumes_quota=True
    )
    excess = max(consuming.count() - allocation.quota, 0)
    if excess == 0:
        raise DomainError("AUTOMATION_OVERAGE_CHANGED", "地区已无超额服务器", status_code=409)
    oldest_id = consuming.order_by("created_at", "pk").values_list("pk", flat=True).first()
    if node.pk != oldest_id:
        raise DomainError(
            "AUTOMATION_OVERAGE_CHANGED", "目标不再是地区内最早的超额服务器", status_code=409
        )
    if not has_subscription_endpoint_fallback(node):
        raise DomainError(
            "AUTOMATION_SUBSCRIPTION_FALLBACK_REQUIRED",
            "删除后活跃订阅将没有可发布节点",
            status_code=409,
        )

    other_deletes = Operation.objects.filter(
        kind="node.delete",
        target_type="node",
        target_id=node.pk,
    ).exclude(pk=operation.pk).exclude(status__in=Operation.TERMINAL_STATUSES)
    if other_deletes.exists():
        raise DomainError(
            "AUTOMATION_OPERATION_IN_FLIGHT", "该服务器已有删除操作", status_code=409
        )


@transaction.atomic
def validate_automated_restart(
    operation: Operation, node: ManagedNode, policy_version: int
) -> None:
    automation = operation.params.get("automation")
    phase = automation.get("phase", "reboot") if isinstance(automation, dict) else None
    expected_kind = {
        "stop": "node.stop",
        "start": "node.start",
        "reboot": "node.reboot",
    }.get(phase)
    if (
        operation.kind != expected_kind
        or operation.target_type != "node"
        or operation.target_id != node.pk
        or not isinstance(automation, dict)
        or automation.get("kind") != "daily_restart"
        or isinstance(policy_version, bool)
        or not isinstance(policy_version, int)
        or automation.get("policy_version") != policy_version
    ):
        raise DomainError("AUTOMATION_POLICY_STALE", "每日重启策略已变化", status_code=409)

    setting = NodeAutomationSetting.objects.select_for_update().filter(singleton_key=1).first()
    node = ManagedNode.objects.select_for_update().get(pk=node.pk)
    local_date_text = str(automation.get("local_date") or "")
    try:
        scheduled_date = datetime.strptime(local_date_text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise DomainError("AUTOMATION_POLICY_STALE", "每日重启日期无效", status_code=409) from exc
    now = timezone.now()
    if timezone.is_naive(now):
        raise DomainError("AUTOMATION_POLICY_STALE", "当前时间缺少时区", status_code=409)
    if (
        local_date_text != scheduled_date.isoformat()
        or operation.params.get("region") != node.region
        or operation.params.get("account_id") != str(node.cloud_account_id)
    ):
        raise DomainError("AUTOMATION_POLICY_STALE", "每日重启策略已变化", status_code=409)

    if phase in {"stop", "reboot"}:
        if setting is None:
            raise DomainError("AUTOMATION_POLICY_STALE", "每日重启策略已变化", status_code=409)
        try:
            current_local_date = now.astimezone(ZoneInfo(setting.daily_restart_timezone)).date()
        except (AttributeError, ValueError, ZoneInfoNotFoundError) as exc:
            raise DomainError(
                "AUTOMATION_POLICY_STALE", "每日重启时区无效", status_code=409
            ) from exc
        if (
            current_local_date != scheduled_date
            or not setting.daily_restart_enabled
            or setting.policy_version != policy_version
            or setting.daily_restart_last_local_date != scheduled_date
            or setting.daily_restart_last_node_id != node.pk
        ):
            raise DomainError("AUTOMATION_POLICY_STALE", "每日重启策略已变化", status_code=409)
    elif phase == "start":
        stop_completed = Operation.objects.filter(
            kind="node.stop",
            target_type="node",
            target_id=node.pk,
            status="SUCCEEDED",
            params__automation__kind="daily_restart",
            params__automation__phase="stop",
            params__automation__local_date=local_date_text,
            params__automation__policy_version=policy_version,
            params__region=node.region,
            params__account_id=str(node.cloud_account_id),
        ).exists()
        if not stop_completed:
            raise DomainError(
                "AUTOMATION_POLICY_STALE", "每日重启停机阶段尚未确认", status_code=409
            )

    if (
        node.desired_state != "PRESENT"
        or node.provisioning_state != "READY"
        or node.security_state != "OPEN"
        or node.observation_error
    ):
        raise DomainError(
            "AUTOMATION_TARGET_INELIGIBLE", "每日重启目标状态已变化", status_code=409
        )
    if phase in {"stop", "reboot"} and (
        node.health_state != "HEALTHY" or node.raw_cloud_state.casefold() != "running"
    ):
        raise DomainError(
            "AUTOMATION_TARGET_INELIGIBLE", "每日重启目标状态已变化", status_code=409
        )
    if phase == "start" and node.raw_cloud_state.casefold() != "stopped":
        raise DomainError(
            "AUTOMATION_TARGET_INELIGIBLE", "每日重启目标尚未确认停机", status_code=409
        )
    if not any(
        isinstance(address, dict)
        and address.get("family", 4) == 4
        and address.get("kind") == "dynamic"
        and address.get("value")
        for address in node.addresses or []
    ):
        raise DomainError(
            "AUTOMATION_TARGET_INELIGIBLE", "每日重启目标缺少旧动态 IPv4", status_code=409
        )

    from apps.nodes.models import NodeConfigRevision
    from apps.nodes.probes import configured_health_probe

    if configured_health_probe() is None:
        raise DomainError(
            "AUTOMATION_HEALTH_PROBE_UNAVAILABLE",
            "未配置可信健康探测，不能执行每日重启",
            status_code=409,
        )
    if (
        node.desired_generation != node.applied_generation
        or not NodeConfigRevision.objects.filter(
            node=node,
            generation=node.applied_generation,
            usable=True,
        ).exists()
    ):
        raise DomainError(
            "AUTOMATION_TARGET_INELIGIBLE", "每日重启目标缺少可用配置", status_code=409
        )
