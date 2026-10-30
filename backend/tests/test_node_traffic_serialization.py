from datetime import timedelta

import pytest
from django.utils import timezone

from apps.nodes.models import NodeProtocol
from apps.nodes.serializers import node_representation, with_node_traffic
from apps.subscriptions.models import AccessProfile, NodeCredential, UsageCheckpoint


@pytest.mark.django_db
def test_node_representation_sums_usage_epochs_and_keeps_latest_sample(prepared_node):
    node, _operation = prepared_node
    profile = AccessProfile.objects.create(name="traffic profile")
    first_sample = timezone.now() - timedelta(minutes=3)
    latest_sample = timezone.now() - timedelta(minutes=1)
    UsageCheckpoint.objects.create(
        node=node,
        profile=profile,
        epoch="boot-a:1:1",
        sequence=1,
        upload_bytes=120,
        download_bytes=340,
        sampled_at=first_sample,
    )
    UsageCheckpoint.objects.create(
        node=node,
        profile=profile,
        epoch="boot-b:2:1",
        sequence=1,
        upload_bytes=50,
        download_bytes=90,
        sampled_at=latest_sample,
    )

    annotated = with_node_traffic(type(node).objects.filter(pk=node.pk)).get()
    result = node_representation(annotated)

    assert result["traffic_upload_bytes"] == 170
    assert result["traffic_download_bytes"] == 430
    assert result["traffic_total_bytes"] == 600
    assert result["traffic_sampled_at"] == latest_sample.isoformat()
    assert result["traffic_state"] == "COLLECTED"
    assert result["metering_coverage"] == "SUPPORTED"


@pytest.mark.django_db
def test_node_representation_marks_traffic_as_not_collected(prepared_node):
    node, _operation = prepared_node

    result = node_representation(node)

    assert result["traffic_upload_bytes"] == 0
    assert result["traffic_download_bytes"] == 0
    assert result["traffic_total_bytes"] == 0
    assert result["traffic_sampled_at"] is None
    assert result["traffic_state"] == "NO_DATA"
    assert result["metering_coverage"] == "SUPPORTED"


@pytest.mark.django_db
def test_node_representation_normalizes_legacy_lightsail_state_object(prepared_node):
    node, _operation = prepared_node
    node.raw_cloud_state = "{'code': 16, 'name': 'running'}"
    node.save(update_fields=["raw_cloud_state", "updated_at"])

    result = node_representation(node)

    assert result["raw_cloud_state"] == "running"


@pytest.mark.django_db
def test_active_socks5_credentials_mark_server_traffic_coverage_partial(prepared_node):
    node, _operation = prepared_node
    profile = AccessProfile.objects.create(name="socks5 profile")
    protocol = NodeProtocol.objects.create(
        node=node,
        protocol="socks5",
        port=1080,
    )
    NodeCredential.objects.create(
        profile=profile,
        node=node,
        protocol=protocol,
        version=1,
        encrypted_material={},
        desired_generation=0,
    )

    result = node_representation(node)

    assert result["metering_coverage"] == "PARTIAL"
