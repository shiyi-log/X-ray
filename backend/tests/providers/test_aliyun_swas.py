from unittest.mock import Mock
from uuid import uuid4

import pytest
from alibabacloud_swas_open20200601.models import (
    ListInstancesResponse,
    ListInstancesResponseBody,
    ListInstancesResponseBodyInstances,
    ListRegionsResponse,
    ListRegionsResponseBody,
    ListRegionsResponseBodyRegions,
)

from common.errors import DomainError
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


def test_list_regions_uses_sdk_request_and_maps_real_region_model():
    ref = AccountRef(uuid4(), "aliyun_swas", "123456789", 1)
    swas = Mock()
    swas.list_regions.return_value = ListRegionsResponse(
        body=ListRegionsResponseBody(
            regions=[ListRegionsResponseBodyRegions(region_id="cn-hongkong", local_name="香港")]
        )
    )
    provider = AliyunSwasProvider(
        ref,
        "cn-hongkong",
        swas_client=swas,
        sts_client=Mock(),
        authorizer=DenyWrites(),
    )

    regions = provider.list_regions()

    assert [(region.id, region.name) for region in regions] == [("cn-hongkong", "香港")]
    assert swas.list_regions.call_args.args[0].to_map() == {}


def test_list_regions_rejects_duplicate_region_ids():
    ref = AccountRef(uuid4(), "aliyun_swas", "123456789", 1)
    swas = Mock()
    swas.list_regions.return_value = {
        "body": {
            "regions": [
                {"region_id": "cn-hongkong"},
                {"region_id": "cn-hongkong"},
            ]
        }
    }
    provider = AliyunSwasProvider(
        ref,
        "cn-hongkong",
        swas_client=swas,
        sts_client=Mock(),
        authorizer=DenyWrites(),
    )

    with pytest.raises(DomainError) as caught:
        provider.list_regions()

    assert caught.value.code == "CLOUD_INVENTORY_RESPONSE_INVALID"


def test_list_instances_pages_to_total_count_and_keeps_all_resources():
    ref = AccountRef(uuid4(), "aliyun_swas", "123456789", 1)
    swas = Mock()
    swas.list_instances.side_effect = [
        ListInstancesResponse(
            body=ListInstancesResponseBody(
                instances=[
                    ListInstancesResponseBodyInstances(
                        instance_id="managed-1", status="Running"
                    )
                ],
                total_count=2,
            )
        ),
        ListInstancesResponse(
            body=ListInstancesResponseBody(
                instances=[
                    ListInstancesResponseBodyInstances(
                        instance_id="manual-1", status="Stopped"
                    )
                ],
                total_count=2,
            )
        ),
    ]
    provider = AliyunSwasProvider(
        ref,
        "cn-hongkong",
        swas_client=swas,
        sts_client=Mock(),
        authorizer=DenyWrites(),
    )

    instances = provider.list_instances("cn-hongkong")

    assert [instance.ref.resource_id for instance in instances] == ["managed-1", "manual-1"]
    assert instances[0].name == "managed-1"
    assert instances[0].state == "Running"
    requests = [call.args[0] for call in swas.list_instances.call_args_list]
    assert [request.page_number for request in requests] == [1, 2]
    assert all(request.region_id == "cn-hongkong" for request in requests)
    assert all(request.page_size == 100 for request in requests)


def test_list_instances_rejects_other_region_before_cloud_read():
    ref = AccountRef(uuid4(), "aliyun_swas", "123456789", 1)
    swas = Mock()
    provider = AliyunSwasProvider(
        ref,
        "cn-hongkong",
        swas_client=swas,
        sts_client=Mock(),
        authorizer=DenyWrites(),
    )

    from common.errors import DomainError

    try:
        provider.list_instances("cn-shanghai")
    except DomainError as exc:
        assert exc.code == "REGION_MISMATCH"
    else:
        raise AssertionError("expected region validation")
    swas.list_instances.assert_not_called()


def test_list_instances_rejects_empty_page_before_reported_total():
    ref = AccountRef(uuid4(), "aliyun_swas", "123456789", 1)
    swas = Mock()
    swas.list_instances.side_effect = [
        ListInstancesResponse(
            body=ListInstancesResponseBody(
                instances=[ListInstancesResponseBodyInstances(instance_id="first")],
                total_count=2,
            )
        ),
        ListInstancesResponse(body=ListInstancesResponseBody(instances=[], total_count=2)),
    ]
    provider = AliyunSwasProvider(
        ref, "cn-hongkong", swas_client=swas, sts_client=Mock(), authorizer=DenyWrites()
    )

    from common.errors import DomainError

    try:
        provider.list_instances("cn-hongkong")
    except DomainError as exc:
        assert exc.code == "CLOUD_INVENTORY_PAGINATION_INVALID"
    else:
        raise AssertionError("incomplete SWAS listing must fail closed")


def test_list_instances_rejects_malformed_count_and_duplicate_ids():
    ref = AccountRef(uuid4(), "aliyun_swas", "123456789", 1)
    provider = AliyunSwasProvider(
        ref, "cn-hongkong", swas_client=Mock(), sts_client=Mock(), authorizer=DenyWrites()
    )
    from common.errors import DomainError

    provider.swas.list_instances.return_value = {
        "body": {"instances": [{"instance_id": "same"}], "total_count": "bad"}
    }
    try:
        provider.list_instances("cn-hongkong")
    except DomainError as exc:
        assert exc.code == "CLOUD_INVENTORY_PAGINATION_INVALID"
    else:
        raise AssertionError("malformed SWAS count must fail closed")

    provider.swas.list_instances.return_value = ListInstancesResponse(
        body=ListInstancesResponseBody(instances=[], total_count=True)
    )
    try:
        provider.list_instances("cn-hongkong")
    except DomainError as exc:
        assert exc.code == "CLOUD_INVENTORY_PAGINATION_INVALID"
    else:
        raise AssertionError("boolean SWAS count must fail closed")

    provider.swas.list_instances.side_effect = [
        ListInstancesResponse(
            body=ListInstancesResponseBody(
                instances=[ListInstancesResponseBodyInstances(instance_id="same")],
                total_count=2,
            )
        ),
        ListInstancesResponse(
            body=ListInstancesResponseBody(
                instances=[ListInstancesResponseBodyInstances(instance_id="same")],
                total_count=2,
            )
        ),
    ]
    try:
        provider.list_instances("cn-hongkong")
    except DomainError as exc:
        assert exc.code == "CLOUD_INVENTORY_RESPONSE_INVALID"
    else:
        raise AssertionError("duplicate SWAS resource IDs must fail closed")


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
