from unittest.mock import Mock
from uuid import uuid4

from providers.aliyun_swas import AliyunSwasProvider
from providers.authorization import DenyWrites
from providers.base import AccountRef
from providers.capabilities import capabilities_for


def test_maps_aliyun_identity_without_default_credential_chain():
    ref = AccountRef(uuid4(), "aliyun_swas", "123456789", 1)
    sts = Mock()
    sts.get_caller_identity.return_value = {
        "body": {"AccountId": "123456789", "PrincipalId": "principal"}
    }
    provider = AliyunSwasProvider(
        ref,
        "cn-hongkong",
        swas_client=Mock(),
        sts_client=sts,
        authorizer=DenyWrites(),
    )
    identity = provider.validate_credentials()
    assert identity.external_account_id == "123456789"
    assert identity.principal_id == "principal"


def test_swas_capability_does_not_claim_live_ip_rotation():
    capabilities = {item.name: item for item in capabilities_for("aliyun_swas", "cn-hongkong")}
    assert capabilities["rotate_public_ip"].status == "UNSUPPORTED"
    assert capabilities["rotate_public_ip"].live_verified is False


def test_all_supported_capabilities_are_documented_and_stubbed():
    for provider in ("aws_lightsail", "aliyun_swas"):
        for capability in capabilities_for(provider, "test-region"):
            if capability.status == "SUPPORTED":
                assert capability.document_verified is True
                assert capability.stub_verified is True
                assert capability.live_verified is False
