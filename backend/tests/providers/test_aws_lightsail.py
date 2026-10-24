from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from common.errors import DomainError
from django.utils import timezone
from providers.authorization import DenyWrites, StaticWriteAuthorizer
from providers.aws_lightsail import AwsLightsailProvider
from providers.base import AccountRef, MutationPermit, ResourceRef


def account():
    return AccountRef(uuid4(), "aws_lightsail", "111111111111", 1)


def test_maps_aws_identity_and_regions_without_network():
    ref = account()
    sts = Mock()
    sts.get_caller_identity.return_value = {
        "Account": ref.external_account_id,
        "Arn": "arn:aws:iam::111111111111:user/test",
    }
    lightsail = Mock()
    lightsail.get_regions.return_value = {"regions": [{"name": "ap-northeast-1"}]}
    provider = AwsLightsailProvider(
        ref,
        "ap-northeast-1",
        lightsail_client=lightsail,
        sts_client=sts,
        authorizer=DenyWrites(),
    )
    assert provider.validate_credentials().external_account_id == "111111111111"
    assert provider.list_regions()[0].id == "ap-northeast-1"


def test_bundle_pagination_preserves_unknown_price():
    ref = account()
    lightsail = Mock()
    lightsail.get_bundles.side_effect = [
        {
            "bundles": [{"bundleId": "small", "price": 5, "transferPerMonthGb": 1000}],
            "nextPageToken": "next",
        },
        {"bundles": [{"bundleId": "unknown"}]},
    ]
    provider = AwsLightsailProvider(
        ref,
        "ap-northeast-1",
        lightsail_client=lightsail,
        sts_client=Mock(),
        authorizer=DenyWrites(),
    )
    plans = provider.list_plans("ap-northeast-1")
    assert [plan.id for plan in plans] == ["small", "unknown"]
    assert plans[0].price is not None
    assert plans[1].price is None
    assert "price unavailable" in plans[1].exclusions


def test_accepted_stop_is_not_reported_completed():
    ref = account()
    resource = ResourceRef(ref, "ap-northeast-1", "node-1")
    permit = MutationPermit(
        uuid4(),
        "op",
        "stop",
        ref.id,
        ref.external_account_id,
        resource.region,
        resource.resource_id,
        timezone.now() + timedelta(minutes=1),
        1,
    )
    lightsail = Mock()
    lightsail.get_instance.return_value = {
        "instance": {
            "name": "node-1",
            "state": "running",
            "tags": [{"key": "xray-manager", "value": "true"}],
        }
    }
    lightsail.stop_instance.return_value = {"ResponseMetadata": {"RequestId": "request-1"}}
    provider = AwsLightsailProvider(
        ref,
        resource.region,
        lightsail_client=lightsail,
        sts_client=Mock(),
        authorizer=StaticWriteAuthorizer(permit),
    )
    result = provider.stop_instance(resource, permit=permit)
    assert result.outcome == "accepted"
    assert result.request_id == "request-1"
    assert lightsail.stop_instance.call_count == 1


def test_cross_region_resource_is_rejected_before_sdk():
    ref = account()
    client = Mock()
    provider = AwsLightsailProvider(
        ref,
        "ap-northeast-1",
        lightsail_client=client,
        sts_client=Mock(),
        authorizer=DenyWrites(),
    )
    resource = ResourceRef(ref, "us-east-1", "node-1")
    with pytest.raises(DomainError) as caught:
        provider.get_instance(resource)
    assert caught.value.code == "RESOURCE_OWNERSHIP_MISMATCH"
    client.get_instance.assert_not_called()


def test_instance_absence_maps_to_explicit_not_found():
    ref = account()
    lightsail = Mock()
    lightsail.get_instance.side_effect = ClientError(
        {"Error": {"Code": "NotFoundException", "Message": "not echoed"},
         "ResponseMetadata": {"RequestId": "absence-request"}},
        "GetInstance",
    )
    provider = AwsLightsailProvider(
        ref, "ap-southeast-1", lightsail_client=lightsail, sts_client=Mock(),
    )
    with pytest.raises(DomainError) as caught:
        provider.get_instance(ResourceRef(ref, "ap-southeast-1", "owned-test"))
    assert caught.value.code == "RESOURCE_NOT_FOUND"
    assert caught.value.status_code == 404
    assert caught.value.details["request_id"] == "absence-request"


def test_write_not_found_does_not_prove_resource_absence():
    from providers.errors import map_provider_error

    error = ClientError({"Error": {"Code": "NotFoundException"}}, "DeleteInstance")
    mapped = map_provider_error("aws_lightsail", error, write_started=True)
    assert mapped.code != "RESOURCE_NOT_FOUND"
