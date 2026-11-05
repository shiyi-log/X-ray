from __future__ import annotations

import os
import re
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db import transaction

from apps.audit.services import AuditService

from .models import (
    NodeAutomationSetting,
    NodeStatusSyncSetting,
    ProviderIdentityNetworkSetting,
)

_ENABLED_ENV_VALUES = {"1", "true", "yes"}
_UNSET = object()


def _environment_provider_identity_network_enabled() -> bool:
    default = "1" if settings.XRAY_ENV == "test" else "0"
    return os.getenv("XRAY_ENABLE_PROVIDER_NETWORK", default).lower() in _ENABLED_ENV_VALUES


def provider_identity_network_setting() -> dict[str, bool | str]:
    setting = ProviderIdentityNetworkSetting.objects.filter(singleton_key=1).first()
    if setting is not None:
        return {"enabled": setting.enabled, "source": "DATABASE"}
    return {
        "enabled": _environment_provider_identity_network_enabled(),
        "source": "ENVIRONMENT",
    }


@transaction.atomic
def set_provider_identity_network_enabled(*, enabled: bool, actor) -> dict[str, bool | str]:
    setting, created = ProviderIdentityNetworkSetting.objects.get_or_create(
        singleton_key=1,
        defaults={"enabled": enabled},
    )
    setting = ProviderIdentityNetworkSetting.objects.select_for_update().get(pk=setting.pk)
    previous_enabled = (
        _environment_provider_identity_network_enabled() if created else setting.enabled
    )
    previous_source = "ENVIRONMENT" if created else "DATABASE"
    changed = created or setting.enabled != enabled
    if not created and changed:
        setting.enabled = enabled
        setting.save(update_fields=["enabled", "updated_at"])
    if changed:
        AuditService.append(
            action="system.provider_identity_network.update",
            target_type="system_setting",
            target_id="provider_identity_network",
            result="SUCCEEDED",
            actor=actor,
            metadata={
                "previous_enabled": previous_enabled,
                "previous_source": previous_source,
                "enabled": enabled,
                "source": "DATABASE",
            },
        )
    return {"enabled": setting.enabled, "source": "DATABASE"}


def node_status_sync_setting() -> dict[str, bool | int | str | None]:
    setting = NodeStatusSyncSetting.objects.filter(singleton_key=1).first()
    if setting is None:
        return {
            "enabled": False,
            "interval_minutes": 60,
            "last_scheduled_at": None,
            "source": "DEFAULT",
        }
    return {
        "enabled": setting.enabled,
        "interval_minutes": setting.interval_minutes,
        "last_scheduled_at": (
            setting.last_scheduled_at.isoformat() if setting.last_scheduled_at else None
        ),
        "source": "DATABASE",
    }


@transaction.atomic
def set_node_status_sync_settings(*, actor, enabled=_UNSET, interval_minutes=_UNSET):
    if enabled is not _UNSET and not isinstance(enabled, bool):
        raise ValueError("node_status_sync_enabled must be a boolean")
    if interval_minutes is not _UNSET and (
        isinstance(interval_minutes, bool)
        or not isinstance(interval_minutes, int)
        or not 5 <= interval_minutes <= 1440
    ):
        raise ValueError("node_status_sync_interval_minutes must be between 5 and 1440")

    setting, created = NodeStatusSyncSetting.objects.get_or_create(singleton_key=1)
    setting = NodeStatusSyncSetting.objects.select_for_update().get(pk=setting.pk)
    previous = {
        "enabled": setting.enabled,
        "interval_minutes": setting.interval_minutes,
    }
    if enabled is not _UNSET:
        setting.enabled = enabled
    if interval_minutes is not _UNSET:
        setting.interval_minutes = interval_minutes
    changed = created or previous != {
        "enabled": setting.enabled,
        "interval_minutes": setting.interval_minutes,
    }
    if changed:
        setting.save(update_fields=["enabled", "interval_minutes", "updated_at"])
        AuditService.append(
            action="system.node_status_sync.update",
            target_type="system_setting",
            target_id="node_status_sync",
            result="SUCCEEDED",
            actor=actor,
            metadata={
                "previous": previous,
                "enabled": setting.enabled,
                "interval_minutes": setting.interval_minutes,
            },
        )
    return node_status_sync_setting()


def node_automation_settings() -> dict:
    setting = NodeAutomationSetting.objects.filter(singleton_key=1).first()
    if setting is None:
        setting = NodeAutomationSetting()
        source = "DEFAULT"
    else:
        source = "DATABASE"
    def timestamp(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    return {
        "node_pool_sync": {
            "enabled": setting.pool_sync_enabled,
            "interval_minutes": setting.pool_sync_interval_minutes,
            "creation_templates": setting.pool_sync_creation_templates,
            "last_scheduled_at": timestamp(setting.pool_sync_last_scheduled_at),
            "source": source,
        },
        "node_daily_restart": {
            "enabled": setting.daily_restart_enabled,
            "time": setting.daily_restart_time,
            "timezone": setting.daily_restart_timezone,
            "last_scheduled_at": timestamp(setting.daily_restart_last_scheduled_at),
            "source": source,
        },
        "usage_sync": {
            "enabled": setting.usage_sync_enabled,
            "interval_minutes": setting.usage_sync_interval_minutes,
            "last_scheduled_at": timestamp(setting.usage_sync_last_scheduled_at),
            "source": source,
        },
    }


_AUTOMATION_FIELD_MAP = {
    "node_pool_sync_enabled": "pool_sync_enabled",
    "node_pool_sync_interval_minutes": "pool_sync_interval_minutes",
    "node_pool_sync_creation_templates": "pool_sync_creation_templates",
    "node_daily_restart_enabled": "daily_restart_enabled",
    "node_daily_restart_time": "daily_restart_time",
    "node_daily_restart_timezone": "daily_restart_timezone",
    "usage_sync_enabled": "usage_sync_enabled",
    "usage_sync_interval_minutes": "usage_sync_interval_minutes",
}


def _validate_automation_candidate(candidate: dict) -> dict:
    for field in (
        "pool_sync_enabled",
        "daily_restart_enabled",
        "usage_sync_enabled",
    ):
        if not isinstance(candidate[field], bool):
            raise ValueError(f"{field} must be a boolean")
    for field, minimum, maximum in (
        ("pool_sync_interval_minutes", 5, 1440),
        ("usage_sync_interval_minutes", 1, 1440),
    ):
        value = candidate[field]
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"{field} must be between {minimum} and {maximum}")

    restart_time = candidate["daily_restart_time"]
    if not isinstance(restart_time, str) or not re.fullmatch(
        r"(?:[01]\d|2[0-3]):[0-5]\d", restart_time
    ):
        raise ValueError("daily_restart_time must use HH:MM in 24-hour time")
    timezone_name = candidate["daily_restart_timezone"]
    if not isinstance(timezone_name, str) or not timezone_name.strip():
        raise ValueError("daily_restart_timezone must be an IANA timezone")
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("daily_restart_timezone must be an IANA timezone") from exc

    templates = candidate["pool_sync_creation_templates"]
    if not isinstance(templates, list):
        raise ValueError("pool_sync_creation_templates must be a list")
    from apps.cloud_accounts.models import CloudAccount
    from common.regions import normalize_region

    normalized = []
    seen_regions = set()
    template_keys = {"region", "cloud_account_id", "plan_id", "image_id"}
    for item in templates:
        if not isinstance(item, dict) or set(item) != template_keys:
            raise ValueError(
                "each creation template requires region, cloud_account_id, plan_id, and image_id"
            )
        region = normalize_region(item["region"])
        if region in seen_regions:
            raise ValueError("creation template regions must be unique")
        seen_regions.add(region)
        try:
            account_id = UUID(str(item["cloud_account_id"]))
        except (TypeError, ValueError) as exc:
            raise ValueError("cloud_account_id must be a UUID") from exc
        account = CloudAccount.objects.filter(pk=account_id, enabled=True).first()
        if (
            account is None
            or not account.credential_versions.filter(version=account.credential_version).exists()
        ):
            raise ValueError(
                "creation template must reference an enabled account with a current credential"
            )
        for field in ("plan_id", "image_id"):
            value = item[field]
            if not isinstance(value, str) or not value.strip() or len(value) > 160:
                raise ValueError(f"{field} must be a non-empty string of at most 160 characters")
        normalized.append(
            {
                "region": region,
                "cloud_account_id": str(account_id),
                "plan_id": item["plan_id"].strip(),
                "image_id": item["image_id"].strip(),
            }
        )
    candidate["pool_sync_creation_templates"] = normalized

    if candidate["pool_sync_enabled"]:
        from apps.nodes.models import NodePool
        from apps.nodes.quota import ensure_pool_allocations

        pool = NodePool.objects.filter(singleton_key=1).first()
        if pool is None or not pool.allow_create:
            raise ValueError("pool synchronization requires an existing pool with creation enabled")
        required_regions = {row.region for row in ensure_pool_allocations(pool) if row.quota > 0}
        if not required_regions.issubset(seen_regions):
            raise ValueError("a creation template is required for each allocated region")
    return candidate


@transaction.atomic
def set_node_automation_settings(*, actor, values: dict) -> dict:
    unknown = set(values) - set(_AUTOMATION_FIELD_MAP)
    if unknown:
        raise ValueError(f"unsupported automation settings: {sorted(unknown)}")
    setting, created = NodeAutomationSetting.objects.get_or_create(singleton_key=1)
    setting = NodeAutomationSetting.objects.select_for_update().get(pk=setting.pk)
    fields = list(_AUTOMATION_FIELD_MAP.values())
    previous = {field: getattr(setting, field) for field in fields}
    candidate = dict(previous)
    for request_field, model_field in _AUTOMATION_FIELD_MAP.items():
        if request_field in values:
            candidate[model_field] = values[request_field]
    candidate = _validate_automation_candidate(candidate)
    changed_fields = [field for field in fields if previous[field] != candidate[field]]
    changed = created or bool(changed_fields)
    if changed:
        for field in fields:
            setattr(setting, field, candidate[field])
        setting.policy_version += 1
        setting.save(update_fields=fields + ["policy_version", "updated_at"])
        AuditService.append(
            action="system.node_automation.update",
            target_type="system_setting",
            target_id="node_automation",
            result="SUCCEEDED",
            actor=actor,
            metadata={
                "changed_fields": changed_fields,
                "policy_version": setting.policy_version,
                "pool_sync_enabled": setting.pool_sync_enabled,
                "daily_restart_enabled": setting.daily_restart_enabled,
                "usage_sync_enabled": setting.usage_sync_enabled,
            },
        )
    return node_automation_settings()
