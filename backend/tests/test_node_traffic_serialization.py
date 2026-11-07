from datetime import timedelta
from uuid import UUID

import pytest
from django.utils import timezone

from apps.nodes.models import NodeProtocol
from apps.nodes.serializers import node_representation, with_node_traffic
from apps.subscriptions.credentials import CredentialService, decrypt_material
from apps.subscriptions.metering import ingest_snapshot
from apps.subscriptions.models import AccessProfile, UsageCheckpoint
from apps.subscriptions.serializers import profile_representation


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
def test_socks5_stats_are_mapped_to_profile_and_added_once(prepared_node):
    node, _operation = prepared_node
    profile = AccessProfile.objects.create(name="socks5 metering profile")
    socks = NodeProtocol.objects.create(node=node, protocol="socks5", port=1080)
    credential = CredentialService.rotate(
        node.pk,
        profile_ids=[profile.pk],
        protocol_ids=[socks.pk],
    )[0]
    username = decrypt_material(credential)["username"]
    snapshot = {
        "generation": node.applied_generation,
        "boot_id": "boot-socks",
        "process_id": "xray-1",
        "sequence": 1,
        "sampled_at": timezone.now().isoformat(),
        "stat": [
            {
                "name": f"user>>>profile-{profile.pk}>>>traffic>>>uplink",
                "value": "20",
            },
            {
                "name": f"user>>>profile-{profile.pk}>>>traffic>>>downlink",
                "value": "30",
            },
            {"name": f"user>>>{username}>>>traffic>>>uplink", "value": "10"},
            {"name": f"user>>>{username}>>>traffic>>>downlink", "value": "40"},
        ],
    }

    assert ingest_snapshot(node, snapshot) == 1
    assert ingest_snapshot(node, {**snapshot, "sequence": 2}) == 1

    profile.refresh_from_db()
    result = node_representation(node)

    assert profile.upload_bytes == 30
    assert profile.download_bytes == 70
    assert result["traffic_upload_bytes"] == 30
    assert result["traffic_download_bytes"] == 70
    assert result["traffic_total_bytes"] == 100
    assert result["metering_coverage"] == "SUPPORTED"
    assert profile_representation(profile)["metering_coverage"] == "SUPPORTED"


@pytest.mark.django_db
def test_colliding_legacy_socks_usernames_are_not_attributed(prepared_node):
    node, _operation = prepared_node
    profiles = [
        AccessProfile.objects.create(
            id=UUID("aaaaaaaa-aaaa-4000-8000-000000000001"), name="first collision profile"
        ),
        AccessProfile.objects.create(
            id=UUID("aaaaaaaa-aaaa-4000-8000-000000000002"), name="second collision profile"
        ),
    ]
    protocol = NodeProtocol.objects.create(node=node, protocol="socks5", port=1081)
    credentials = CredentialService.rotate(
        node.pk,
        profile_ids=[profile.pk for profile in profiles],
        protocol_ids=[protocol.pk],
    )
    usernames = {decrypt_material(credential)["username"] for credential in credentials}
    assert len(usernames) == 1
    username = usernames.pop()
    snapshot = {
        "generation": node.applied_generation,
        "boot_id": "boot-collision",
        "process_id": "xray-1",
        "sequence": 1,
        "sampled_at": timezone.now().isoformat(),
        "stat": [{"name": f"user>>>{username}>>>traffic>>>uplink", "value": 100}],
    }

    assert ingest_snapshot(node, snapshot) == 0
    assert node_representation(node)["metering_coverage"] == "PARTIAL"
    for profile in profiles:
        profile.refresh_from_db()
        assert profile.upload_bytes == 0
        assert profile_representation(profile)["metering_coverage"] == "PARTIAL"
