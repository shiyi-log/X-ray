from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from django.utils import timezone

from common.errors import DomainError
from providers.authorization import DenyWrites, StaticWriteAuthorizer
from providers.aws_lightsail import AwsLightsailProvider
from providers.base import AccountRef, FirewallRule, MutationPermit, ResourceRef


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


def test_maps_lightsail_state_object_to_its_name():
    ref = account()
    provider = AwsLightsailProvider(
        ref,
        "ap-southeast-1",
        lightsail_client=Mock(),
        sts_client=Mock(),
        authorizer=DenyWrites(),
    )

    instance = provider._map_instance(
        {
            "name": "node-1",
            "state": {"code": 16, "name": "running"},
            "publicIpAddress": "203.0.113.10",
            "tags": [],
        }
    )

    assert instance.state == "running"
    assert instance.raw_state == "running"
    assert [(address.value, address.family) for address in instance.addresses] == [
        ("203.0.113.10", 4)
    ]


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
    lightsail.stop_instance.return_value = {
        "ResponseMetadata": {"RequestId": "request-1"},
        "operations": [
            {
                "id": "operation-1",
                "resourceName": "node-1",
                "resourceType": "Instance",
                "operationType": "StopInstance",
            }
        ],
    }
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
    assert result.operation_id == "operation-1"
    assert lightsail.stop_instance.call_count == 1


@pytest.mark.parametrize(
    ("aws_status", "expected"),
    [
        ("NotStarted", "IN_PROGRESS"),
        ("Started", "IN_PROGRESS"),
        ("Succeeded", "SUCCEEDED"),
        ("Completed", "SUCCEEDED"),
        ("Failed", "FAILED"),
    ],
)
def test_get_operation_status_maps_exact_reboot_operation(aws_status, expected):
    ref = account()
    resource = ResourceRef(ref, "ap-southeast-1", "node-1")
    lightsail = Mock()
    lightsail.get_operation.return_value = {
        "operation": {
            "id": "operation-1",
            "resourceName": "node-1",
            "resourceType": "Instance",
            "operationType": "RebootInstance",
            "status": aws_status,
        }
    }
    provider = AwsLightsailProvider(
        ref,
        resource.region,
        lightsail_client=lightsail,
        sts_client=Mock(),
    )

    assert provider.get_operation_status("operation-1", resource, action="reboot") == expected
    lightsail.get_operation.assert_called_once_with(operationId="operation-1")


def test_get_operation_status_rejects_another_resource():
    ref = account()
    resource = ResourceRef(ref, "ap-southeast-1", "node-1")
    lightsail = Mock()
    lightsail.get_operation.return_value = {
        "operation": {
            "id": "operation-1",
            "resourceName": "another-node",
            "resourceType": "Instance",
            "operationType": "RebootInstance",
            "status": "Succeeded",
        }
    }
    provider = AwsLightsailProvider(
        ref,
        resource.region,
        lightsail_client=lightsail,
        sts_client=Mock(),
    )

    with pytest.raises(DomainError) as caught:
        provider.get_operation_status("operation-1", resource, action="reboot")

    assert caught.value.code == "CLOUD_OPERATION_TARGET_MISMATCH"


def test_list_operation_ids_snapshots_only_matching_action_across_pages():
    ref = account()
    resource = ResourceRef(ref, "ap-southeast-1", "node-1")
    lightsail = Mock()
    lightsail.get_operations_for_resource.side_effect = [
        {
            "operations": [
                {
                    "id": "existing-start",
                    "resourceName": "node-1",
                    "resourceType": "Instance",
                    "operationType": "StartInstance",
                },
                {
                    "id": "other-action",
                    "resourceName": "node-1",
                    "resourceType": "Instance",
                    "operationType": "RebootInstance",
                },
            ],
            "nextPageToken": "next",
        },
        {
            "operations": [
                {
                    "id": "other-resource",
                    "resourceName": "node-2",
                    "resourceType": "Instance",
                    "operationType": "StartInstance",
                },
                {
                    "id": "existing-start-2",
                    "resourceName": "node-1",
                    "resourceType": "Instance",
                    "operationType": "StartInstance",
                },
            ]
        },
    ]
    provider = AwsLightsailProvider(
        ref,
        resource.region,
        lightsail_client=lightsail,
        sts_client=Mock(),
    )

    assert provider.list_operation_ids(resource, action="start") == [
        "existing-start",
        "existing-start-2",
    ]
    assert lightsail.get_operations_for_resource.call_count == 2
    assert lightsail.get_operations_for_resource.call_args_list[0].kwargs == {
        "resourceName": "node-1"
    }
    assert lightsail.get_operations_for_resource.call_args_list[1].kwargs == {
        "resourceName": "node-1",
        "pageToken": "next",
    }


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


def test_configure_firewall_preserves_ipv4_and_ipv6_in_one_replacement():
    ref = account()
    resource = ResourceRef(ref, "ap-southeast-1", "node-1")
    permit = MutationPermit(
        uuid4(),
        "op",
        "firewall",
        ref.id,
        ref.external_account_id,
        resource.region,
        resource.resource_id,
        timezone.now() + timedelta(minutes=1),
        1,
    )
    lightsail = Mock()
    lightsail.get_instance.return_value = {
        "instance": {"name": "node-1", "state": "running", "tags": []}
    }
    lightsail.put_instance_public_ports.return_value = {
        "ResponseMetadata": {"RequestId": "firewall-request"}
    }
    provider = AwsLightsailProvider(
        ref,
        resource.region,
        lightsail_client=lightsail,
        sts_client=Mock(),
        authorizer=StaticWriteAuthorizer(permit),
    )

    result = provider.configure_firewall(
        resource,
        (
            FirewallRule("tcp", 80, 80, "0.0.0.0/0", "cidr", 4),
            FirewallRule("tcp", 80, 80, "::/0", "cidr", 6),
        ),
        permit=permit,
    )

    assert result.request_id == "firewall-request"
    lightsail.put_instance_public_ports.assert_called_once_with(
        instanceName="node-1",
        portInfos=[
            {
                "fromPort": 80,
                "toPort": 80,
                "protocol": "tcp",
                "cidrs": ["0.0.0.0/0"],
                "ipv6Cidrs": ["::/0"],
            }
        ],
    )


def test_get_firewall_reads_ipv4_ipv6_and_provider_alias_fields():
    ref = account()
    lightsail = Mock()
    lightsail.get_instance_port_states.return_value = {
        "portStates": [
            {
                "fromPort": 22,
                "toPort": 22,
                "protocol": "tcp",
                "cidrs": ["192.0.2.10/32"],
                "ipv6Cidrs": ["2001:db8::/64"],
                "cidrListAliases": ["lightsail-connect"],
            }
        ],
        "ResponseMetadata": {"RequestId": "readback-request"},
    }
    provider = AwsLightsailProvider(
        ref,
        "ap-southeast-1",
        lightsail_client=lightsail,
        sts_client=Mock(),
        authorizer=DenyWrites(),
    )

    snapshot = provider.get_firewall(ResourceRef(ref, "ap-southeast-1", "node-1"))

    assert snapshot.request_id == "readback-request"
    assert [(rule.family, rule.source_kind, rule.source) for rule in snapshot.rules] == [
        (4, "cidr", "192.0.2.10/32"),
        (6, "cidr", "2001:db8::/64"),
        (4, "provider_alias", "lightsail-connect"),
    ]
