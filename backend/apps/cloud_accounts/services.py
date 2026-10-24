from __future__ import annotations

import json
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import AuditService
from common.crypto import configured_secret_store
from common.errors import DomainError
from common.regions import normalize_region
from providers.base import AccountIdentity, SecretInput
from providers.registry import build_read_provider, provider_for_input

from .models import CloudAccount, CloudCredentialVersion


def _canonical_fields(credentials: SecretInput) -> bytes:
    if not credentials.fields:
        raise DomainError("CLOUD_CREDENTIALS_REQUIRED", "必须提供云凭据", status_code=400)
    if any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in credentials.fields.items()
    ):
        raise DomainError("CLOUD_CREDENTIALS_INVALID", "云凭据字段格式无效", status_code=400)
    return json.dumps(dict(credentials.fields), sort_keys=True, separators=(",", ":")).encode()


def _aad(account_id: UUID, version: int) -> bytes:
    return f"cloud-account:{account_id}:credentials:{version}".encode()


def reader_for_input(credentials: SecretInput, region: str):
    return provider_for_input(credentials, normalize_region(region))


def _identity_matches(account: CloudAccount, identity: AccountIdentity) -> bool:
    return (
        identity.provider == account.provider
        and identity.external_account_id == account.external_account_id
    )


def create_account(*, name: str, credentials: SecretInput, region: str) -> CloudAccount:
    region = normalize_region(region)
    if credentials.provider not in dict(CloudAccount.PROVIDER_CHOICES):
        raise DomainError("CLOUD_PROVIDER_UNSUPPORTED", "不支持的云厂商", status_code=400)
    identity = reader_for_input(credentials, region).validate_credentials()
    if identity.provider != credentials.provider:
        raise DomainError("CLOUD_IDENTITY_MISMATCH", "云身份与厂商不匹配", status_code=409)
    account_id = UUID(str(__import__("uuid").uuid4()))
    envelope = configured_secret_store().encrypt(
        _canonical_fields(credentials), purpose="control.cloud_credentials", aad=_aad(account_id, 1)
    )
    try:
        with transaction.atomic():
            account = CloudAccount.objects.create(
                id=account_id,
                name=name.strip() or "未命名云账号",
                provider=credentials.provider,
                external_account_id=identity.external_account_id,
                credential_version=1,
                validated_at=identity.verified_at,
                last_validation_code="OK",
            )
            CloudCredentialVersion.objects.create(
                account=account,
                version=1,
                encrypted_credentials=envelope,
                identity_verified_at=identity.verified_at,
            )
            AuditService.append(
                action="cloud_account.create",
                target_type="CloudAccount",
                target_id=account.pk,
                result="SUCCEEDED",
                metadata={
                    "provider": account.provider,
                    "external_account_id": account.external_account_id,
                },
            )
            return account
    except IntegrityError as exc:
        raise DomainError(
            "CLOUD_ACCOUNT_EXISTS",
            "相同云身份已存在",
            status_code=409,
        ) from exc


def _current_credentials(account: CloudAccount, version: int | None = None) -> SecretInput:
    selected = version or account.credential_version
    record = account.credential_versions.get(version=selected)
    payload = configured_secret_store().decrypt(
        record.encrypted_credentials,
        purpose="control.cloud_credentials",
        aad=_aad(account.pk, selected),
    )
    return SecretInput(provider=account.provider, fields=json.loads(payload.decode()))


def rotate_credentials(
    account_id: UUID,
    *,
    credentials: SecretInput,
    region: str,
    expected_version: int | None = None,
) -> CloudAccount:
    region = normalize_region(region)
    account = CloudAccount.objects.get(pk=account_id)
    if credentials.provider != account.provider:
        raise DomainError("CLOUD_PROVIDER_MISMATCH", "云厂商不能在轮换时改变", status_code=400)
    identity = reader_for_input(credentials, region).validate_credentials()
    if not _identity_matches(account, identity):
        raise DomainError("CLOUD_IDENTITY_MISMATCH", "新凭据指向了不同云身份", status_code=409)
    with transaction.atomic():
        locked = CloudAccount.objects.select_for_update().get(pk=account_id)
        if expected_version is not None and locked.credential_version != expected_version:
            raise DomainError(
                "CLOUD_CREDENTIAL_VERSION_CONFLICT",
                "云凭据版本已被其他操作更新",
                status_code=409,
            )
        new_version = locked.credential_version + 1
        envelope = configured_secret_store().encrypt(
            _canonical_fields(credentials),
            purpose="control.cloud_credentials",
            aad=_aad(locked.pk, new_version),
        )
        CloudCredentialVersion.objects.create(
            account=locked,
            version=new_version,
            encrypted_credentials=envelope,
            identity_verified_at=identity.verified_at,
        )
        locked.credential_version = new_version
        locked.validated_at = identity.verified_at
        locked.last_validation_code = "OK"
        locked.save(
            update_fields=[
                "credential_version",
                "validated_at",
                "last_validation_code",
                "updated_at",
            ]
        )
        AuditService.append(
            action="cloud_account.rotate_credentials",
            target_type="CloudAccount",
            target_id=locked.pk,
            result="SUCCEEDED",
            metadata={"credential_version": new_version},
        )
        return locked


def validate_account(account_id: UUID, *, region: str) -> AccountIdentity:
    region = normalize_region(region)
    account = CloudAccount.objects.get(pk=account_id)
    credentials = _current_credentials(account)
    try:
        identity = reader_for_input(credentials, region).validate_credentials()
    except DomainError as exc:
        CloudAccount.objects.filter(pk=account.pk).update(last_validation_code=exc.code)
        raise
    if not _identity_matches(account, identity):
        CloudAccount.objects.filter(pk=account.pk).update(
            last_validation_code="CLOUD_IDENTITY_MISMATCH"
        )
        raise DomainError("CLOUD_IDENTITY_MISMATCH", "云端返回的身份发生变化", status_code=409)
    CloudAccount.objects.filter(pk=account.pk).update(
        validated_at=identity.verified_at, last_validation_code="OK", updated_at=timezone.now()
    )
    return identity


def set_account_enabled(account_id: UUID, *, enabled: bool) -> CloudAccount:
    account = CloudAccount.objects.get(pk=account_id)
    account.enabled = enabled
    account.save(update_fields=["enabled", "updated_at"])
    AuditService.append(
        action="cloud_account.enable" if enabled else "cloud_account.disable",
        target_type="CloudAccount",
        target_id=account.pk,
        result="SUCCEEDED",
        metadata={"enabled": enabled},
    )
    return account


def capabilities(account_id: UUID, *, region: str):
    region = normalize_region(region)
    provider = build_read_provider(account_id, region)
    return provider.get_capabilities(region)
