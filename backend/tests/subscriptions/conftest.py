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
    from apps.nodes.models import NodeProtocol
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
    ready_node.save(update_fields=["applied_generation", "updated_at"])
    credential.applied_generation = credential.desired_generation
    credential.save(update_fields=["applied_generation"])
    return issued, profile.subscription, ready_node, credential


@pytest.fixture
def revocable_profile(publishable_subscription):
    issued, subscription, node, credential = publishable_subscription
    return issued, subscription.profile, node, credential
