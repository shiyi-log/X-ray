import pytest

from common.errors import DomainError


@pytest.mark.django_db
def test_first_seen_host_key_requires_explicit_approval(prepared_node):
    from apps.nodes.ssh import HostKeyService

    node, _operation = prepared_node
    service = HostKeyService()
    first_fingerprint = "SHA256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    candidate = service.observe(node.pk, first_fingerprint, source="cloud-console")
    assert candidate.status == "CANDIDATE"

    with pytest.raises(DomainError) as caught:
        service.verify(node.pk, first_fingerprint)
    assert caught.value.code == "SSH_HOST_KEY_NOT_APPROVED"

    approved = service.approve(
        candidate.pk,
        expected_fingerprint=first_fingerprint,
        source="administrator",
    )
    assert approved.status == "APPROVED"
    assert service.verify(node.pk, first_fingerprint).pk == approved.pk


@pytest.mark.django_db
def test_changed_host_key_is_rejected_and_recorded(prepared_node):
    from apps.nodes.ssh import HostKeyService

    node, _operation = prepared_node
    service = HostKeyService()
    first_fingerprint = "SHA256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    changed_fingerprint = "SHA256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    first = service.observe(node.pk, first_fingerprint, source="cloud-console")
    service.approve(
        first.pk,
        expected_fingerprint=first_fingerprint,
        source="administrator",
    )

    with pytest.raises(DomainError) as caught:
        service.verify(node.pk, changed_fingerprint)
    assert caught.value.code == "SSH_HOST_KEY_CHANGED"
    assert node.host_keys.filter(
        fingerprint=changed_fingerprint, status="REJECTED"
    ).exists()


@pytest.mark.django_db
def test_provider_attestation_approves_first_key_but_never_rotates_an_approved_key(
    prepared_node,
):
    from apps.nodes.ssh import HostKeyService

    node, _operation = prepared_node
    service = HostKeyService()
    first_fingerprint = "SHA256:ccccccccccccccccccccccccccccccccccccccccccc"
    changed_fingerprint = "SHA256:ddddddddddddddddddddddddddddddddddddddddddd"

    with pytest.raises(DomainError) as untrusted:
        service.verify_provider_attested(
            node.pk,
            first_fingerprint,
            attested_fingerprints=(),
            source="aws-lightsail-access-details",
        )
    assert untrusted.value.code == "SSH_HOST_KEY_NOT_APPROVED"
    assert node.host_keys.filter(
        fingerprint=first_fingerprint, status="CANDIDATE"
    ).exists()

    approved = service.verify_provider_attested(
        node.pk,
        first_fingerprint,
        attested_fingerprints=(first_fingerprint,),
        source="aws-lightsail-access-details",
    )
    assert approved.status == "APPROVED"
    assert approved.source == "aws-lightsail-access-details"

    with pytest.raises(DomainError) as changed:
        service.verify_provider_attested(
            node.pk,
            changed_fingerprint,
            attested_fingerprints=(changed_fingerprint,),
            source="aws-lightsail-access-details",
        )
    assert changed.value.code == "SSH_HOST_KEY_CHANGED"
    assert node.host_keys.filter(
        fingerprint=changed_fingerprint, status="REJECTED"
    ).exists()
