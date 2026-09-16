from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.utils import timezone

from common.errors import DomainError
from providers.aliyun_swas import AliyunSwasProvider
from providers.authorization import DenyWrites
from providers.aws_lightsail import AwsLightsailProvider
from providers.base import AccountRef, MutationPermit, ResourceRef


def _permit(account, action, resource_id=None):
    return MutationPermit(
        uuid4(),
        "operation-key",
        action,
        account.id,
        account.external_account_id,
        "ap-northeast-1",
        resource_id,
        timezone.now() + timedelta(minutes=1),
        1,
    )


def test_denied_aws_write_never_reaches_sdk():
    account = AccountRef(uuid4(), "aws_lightsail", "111111111111", 1)
    client = Mock()
    provider = AwsLightsailProvider(
        account,
        "ap-northeast-1",
        lightsail_client=client,
        sts_client=Mock(),
        authorizer=DenyWrites(),
    )
    resource = ResourceRef(account, "ap-northeast-1", "test-node")
    with pytest.raises(DomainError) as caught:
        provider.stop_instance(resource, permit=_permit(account, "stop", "test-node"))
    assert caught.value.code == "CLOUD_WRITE_NOT_AUTHORIZED"
    assert client.stop_instance.call_count == 0


def test_swas_ip_rotation_is_explicitly_blocked_without_sdk_call():
    account = AccountRef(uuid4(), "aliyun_swas", "test-account", 1)
    client = Mock()
    provider = AliyunSwasProvider(
        account,
        "ap-southeast-1",
        swas_client=client,
        sts_client=Mock(),
        authorizer=DenyWrites(),
    )
    resource = ResourceRef(account, "ap-southeast-1", "test-instance")
    with pytest.raises(DomainError) as caught:
        provider.rotate_public_ip(resource, permit=None)
    assert caught.value.code == "CAPABILITY_UNSUPPORTED"
    assert client.mock_calls == []


def test_expired_static_permit_is_rejected():
    account = AccountRef(uuid4(), "aws_lightsail", "111111111111", 1)
    from providers.authorization import StaticWriteAuthorizer

    permit = MutationPermit(
        uuid4(),
        "operation-key",
        "stop",
        account.id,
        account.external_account_id,
        "ap-northeast-1",
        "node",
        timezone.now() - timedelta(seconds=1),
        1,
    )
    with pytest.raises(DomainError) as caught:
        StaticWriteAuthorizer(permit).assert_allowed(
            permit, action="stop", account=account, resource_id="node"
        )
    assert caught.value.code == "CLOUD_WRITE_NOT_AUTHORIZED"
