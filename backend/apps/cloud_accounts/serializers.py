from __future__ import annotations

from common.regions import normalize_region

from .models import CloudAccount


class CloudAccountSerializer:
    fields = (
        "id",
        "name",
        "provider",
        "external_account_id",
        "credential_version",
        "enabled",
        "validated_at",
        "last_validation_code",
    )

    @classmethod
    def to_representation(cls, account: CloudAccount) -> dict:
        return {
            "id": str(account.pk),
            "name": account.name,
            "provider": account.provider,
            "external_account_id": account.external_account_id,
            "credential_version": account.credential_version,
            "enabled": account.enabled,
            "validated_at": account.validated_at.isoformat() if account.validated_at else None,
            "last_validation_code": account.last_validation_code,
        }

    @classmethod
    def validate_create(cls, payload: dict) -> tuple[str, str, dict]:
        allowed = {"name", "provider", "credentials", "region"}
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"unsupported fields: {sorted(unknown)}")
        name = str(payload.get("name") or "").strip()
        provider = str(payload.get("provider") or "")
        credentials = payload.get("credentials")
        region = normalize_region(payload.get("region"))
        if not name or not provider or not isinstance(credentials, dict):
            raise ValueError("name, provider and credentials are required")
        return name, region, {"provider": provider, "fields": credentials}

    @classmethod
    def validate_patch(cls, payload: dict) -> dict:
        unknown = set(payload) - {"name", "enabled"}
        if unknown:
            raise ValueError(f"unsupported fields: {sorted(unknown)}")
        result = {}
        if "name" in payload:
            name = str(payload["name"]).strip()
            if not name:
                raise ValueError("name cannot be empty")
            result["name"] = name
        if "enabled" in payload:
            if not isinstance(payload["enabled"], bool):
                raise ValueError("enabled must be boolean")
            result["enabled"] = payload["enabled"]
        return result
