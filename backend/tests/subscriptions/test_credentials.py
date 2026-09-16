import json

import pytest


@pytest.mark.django_db
def test_profile_scoped_credentials_are_distinct_and_encrypted(ready_node):
    from apps.nodes.models import NodeProtocol
    from apps.subscriptions.credentials import CredentialService, decrypt_material
    from apps.subscriptions.models import AccessProfile

    protocol = NodeProtocol.objects.create(
        node=ready_node,
        protocol="vless",
        port=443,
        tls_enabled=True,
        server_name="proxy.example.test",
        credential_scope="profile",
    )
    first = AccessProfile.objects.create(name="credential-a")
    second = AccessProfile.objects.create(name="credential-b")
    credentials = CredentialService.rotate(
        ready_node.pk,
        profile_ids=[first.pk, second.pk],
        protocol_ids=[protocol.pk],
    )
    materials = [decrypt_material(value) for value in credentials]
    assert materials[0]["id"] != materials[1]["id"]
    persisted = json.dumps([value.encrypted_material for value in credentials])
    assert materials[0]["id"] not in persisted
    assert materials[1]["id"] not in persisted


@pytest.mark.django_db
def test_shared_rotation_expands_to_every_active_profile(ready_node):
    from apps.nodes.models import NodeProtocol
    from apps.subscriptions.credentials import CredentialService, decrypt_material
    from apps.subscriptions.models import AccessProfile

    protocol = NodeProtocol.objects.create(
        node=ready_node,
        protocol="shadowsocks",
        port=8443,
        method="aes-128-gcm",
        credential_scope="shared",
    )
    requested = AccessProfile.objects.create(name="shared-a")
    affected = AccessProfile.objects.create(name="shared-b")
    revoked = AccessProfile.objects.create(name="shared-revoked", status="REVOKED")
    credentials = CredentialService.rotate(
        ready_node.pk,
        profile_ids=[requested.pk, revoked.pk],
        protocol_ids=[protocol.pk],
    )
    assert {value.profile_id for value in credentials} == {requested.pk, affected.pk}
    materials = [decrypt_material(value) for value in credentials]
    assert materials[0] == materials[1]
    assert all(value.credential_scope == "shared" for value in credentials)
