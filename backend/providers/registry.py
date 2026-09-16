from __future__ import annotations

import json
import os
from uuid import UUID, uuid4

from common.crypto import configured_secret_store
from common.errors import DomainError

from .authorization import DenyWrites
from .base import AccountRef, CloudProvider, CloudReader, SecretInput


class NullProvider:
    """Safe default used until an explicitly configured provider is injected."""

    def __init__(self, account: AccountRef, region: str):
        self.account = account
        self.region = region

    def validate_credentials(self):
        raise DomainError("CLOUD_PROVIDER_NOT_CONFIGURED", "云适配器尚未配置", status_code=503)

    def __getattr__(self, name):
        if name in {
            "create_instance",
            "start_instance",
            "stop_instance",
            "reboot_instance",
            "delete_instance",
            "rotate_public_ip",
            "configure_firewall",
        }:
            raise DomainError("CLOUD_WRITE_NOT_AUTHORIZED", "云写入未配置", status_code=403)
        raise AttributeError(name)


class ReadOnlyProviderProxy:
    _read_methods = {
        "validate_credentials",
        "list_regions",
        "list_plans",
        "list_images",
        "find_instance_by_request",
        "get_instance",
        "get_public_ip",
        "get_firewall",
        "get_capabilities",
    }

    def __init__(self, provider: CloudReader):
        self._provider = provider

    def __getattr__(self, name):
        if name not in self._read_methods:
            raise AttributeError(name)
        return getattr(self._provider, name)


def _credentials_from_envelope(account, version: int | None = None) -> SecretInput:
    selected = version or account.credential_version
    record = account.credential_versions.get(version=selected)
    payload = configured_secret_store().decrypt(
        record.encrypted_credentials,
        purpose="control.cloud_credentials",
        aad=f"cloud-account:{account.pk}:credentials:{selected}".encode(),
    )
    fields = json.loads(payload.decode("utf-8"))
    return SecretInput(provider=account.provider, fields=fields)


def _provider_for_credentials(
    account: AccountRef, region: str, credentials: SecretInput, *, authorizer=None
) -> CloudProvider:
    if credentials.provider == "aws_lightsail":
        from .aws_lightsail import AwsLightsailProvider

        return AwsLightsailProvider.from_credentials(
            account, region, credentials.fields, authorizer=authorizer or DenyWrites()
        )
    if credentials.provider == "aliyun_swas":
        from .aliyun_swas import AliyunSwasProvider

        return AliyunSwasProvider.from_credentials(
            account, region, credentials.fields, authorizer=authorizer or DenyWrites()
        )
    raise DomainError("CLOUD_PROVIDER_UNSUPPORTED", "不支持的云厂商", status_code=400)


def build_read_provider(
    account_id: UUID, region: str, *, credential_version: int | None = None
) -> CloudReader:
    from apps.cloud_accounts.models import CloudAccount

    account = CloudAccount.objects.get(pk=account_id)
    ref = AccountRef(
        account.id,
        account.provider,
        account.external_account_id,
        credential_version or account.credential_version,
    )
    provider = _provider_for_credentials(
        ref, region, _credentials_from_envelope(account, credential_version)
    )
    return ReadOnlyProviderProxy(provider)


def build_write_provider(
    account_id: UUID,
    region: str,
    *,
    authorizer,
    credential_version: int | None = None,
) -> CloudProvider:
    from apps.cloud_accounts.models import CloudAccount

    account = CloudAccount.objects.get(pk=account_id)
    if not account.enabled:
        raise DomainError("CLOUD_ACCOUNT_DISABLED", "云账号已停用", status_code=409)
    selected = credential_version or account.credential_version
    ref = AccountRef(account.id, account.provider, account.external_account_id, selected)
    return _provider_for_credentials(
        ref,
        region,
        _credentials_from_envelope(account, selected),
        authorizer=authorizer,
    )


def provider_for_input(credentials: SecretInput, region: str) -> CloudReader:
    if os.getenv("XRAY_ENABLE_PROVIDER_NETWORK", "0").lower() not in {"1", "true", "yes"}:
        raise DomainError(
            "CLOUD_NETWORK_DISABLED",
            "本地环境默认禁止云网络调用",
            retryable=False,
            status_code=503,
        )
    ref = AccountRef(uuid4(), credentials.provider, "", 1)
    return _provider_for_credentials(ref, region, credentials, authorizer=DenyWrites())
