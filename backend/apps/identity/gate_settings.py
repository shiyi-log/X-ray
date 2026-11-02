from __future__ import annotations

import os

from django.db import transaction

from apps.audit.services import AuditService

from .models import NodeStatusSyncSetting, ProviderIdentityNetworkSetting

_ENABLED_ENV_VALUES = {"1", "true", "yes"}
_UNSET = object()


def _environment_provider_identity_network_enabled() -> bool:
    return os.getenv("XRAY_ENABLE_PROVIDER_NETWORK", "0").lower() in _ENABLED_ENV_VALUES


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
