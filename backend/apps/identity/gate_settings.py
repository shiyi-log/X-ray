from __future__ import annotations

import os

from django.db import transaction

from apps.audit.services import AuditService

from .models import ProviderIdentityNetworkSetting

_ENABLED_ENV_VALUES = {"1", "true", "yes"}


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
