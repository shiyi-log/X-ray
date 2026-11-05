import pytest


@pytest.fixture
def ready_node(prepared_node):
    node, _operation = prepared_node
    node.provisioning_state = "READY"
    node.desired_generation = 1
    node.applied_generation = 1
    node.addresses = [{"value": "192.0.2.50", "family": 4, "kind": "static"}]
    node.save(
        update_fields=[
            "provisioning_state",
            "desired_generation",
            "applied_generation",
            "addresses",
            "updated_at",
        ]
    )
    return node


@pytest.fixture
def publishable_subscription(ready_node):
    from apps.nodes.models import NodeConfigRevision, NodeProtocol
    from apps.subscriptions.credentials import CredentialService
    from apps.subscriptions.models import AccessProfile
    from apps.subscriptions.tokens import TokenService

    protocol = NodeProtocol.objects.create(
        node=ready_node,
        protocol="trojan",
        port=443,
        tls_enabled=True,
        server_name="proxy.example.test",
        credential_scope="profile",
    )
    profile = AccessProfile.objects.create(name="publishable")
    issued = TokenService.issue(profile.pk)
    credential = CredentialService.rotate(
        ready_node.pk,
        profile_ids=[profile.pk],
        protocol_ids=[protocol.pk],
    )[0]
    ready_node.refresh_from_db()
    ready_node.applied_generation = ready_node.desired_generation
    ready_node.raw_cloud_state = "running"
    ready_node.health_state = "HEALTHY"
    ready_node.provisioning_state = "READY"
    ready_node.observation_error = ""
    ready_node.save(
        update_fields=[
            "applied_generation",
            "raw_cloud_state",
            "health_state",
            "provisioning_state",
            "observation_error",
            "updated_at",
        ]
    )
    credential.applied_generation = credential.desired_generation
    credential.save(update_fields=["applied_generation"])
    NodeConfigRevision.objects.update_or_create(
        node=ready_node,
        generation=ready_node.applied_generation,
        defaults={
            "config_hash": "a" * 64,
            "xray_version": "26.3.27",
            "installer_version": "1.0.0",
            "bundle_hash": "test-bundle",
            "usable": True,
            "probe_result": {
                "generation": ready_node.applied_generation,
                "app_health_passed": True,
                "accepted": True,
                "positive_control": True,
                "fresh_connection": True,
            },
        },
    )
    return issued, profile.subscription, ready_node, credential


@pytest.fixture
def revocable_profile(publishable_subscription):
    issued, subscription, node, credential = publishable_subscription
    return issued, subscription.profile, node, credential
