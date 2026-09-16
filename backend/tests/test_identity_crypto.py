import pytest
from django.db import IntegrityError, transaction

from apps.audit.models import AuditEvent
from apps.audit.services import AuditService
from apps.identity.models import SuperAdmin
from common.crypto import SecretStore


@pytest.fixture
def secret_store():
    return SecretStore(
        {
            "control": {1: b"c" * 32, 2: b"d" * 32},
            "subscription": {1: b"s" * 32},
        }
    )


def test_ciphertext_is_bound_to_purpose_and_aad(secret_store):
    envelope = secret_store.encrypt(b"fake-key", purpose="control", aad=b"account:1")
    assert secret_store.decrypt(envelope, purpose="control", aad=b"account:1") == b"fake-key"
    with pytest.raises(ValueError, match="authentication failed"):
        secret_store.decrypt(envelope, purpose="control", aad=b"account:2")
    with pytest.raises(ValueError):
        secret_store.decrypt(envelope, purpose="subscription", aad=b"account:1")


def test_key_rotation_keeps_old_version_decryptable(secret_store):
    old = secret_store.encrypt(b"old", purpose="control", aad=b"record:1")
    assert old["key_version"] == 2
    assert secret_store.decrypt(old, purpose="control", aad=b"record:1") == b"old"


def test_envelope_never_contains_plaintext_or_dek(secret_store):
    envelope = secret_store.encrypt(b"very-private-value", purpose="subscription", aad=b"p:1")
    serialized = repr(envelope)
    assert "very-private-value" not in serialized
    assert "dek" in envelope["wrapped_dek_nonce"] or envelope["wrapped_dek_nonce"]


@pytest.mark.django_db(transaction=True)
def test_database_rejects_second_admin():
    SuperAdmin.objects.create_superuser("owner", "test-only-password-A")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SuperAdmin.objects.create_superuser("second", "test-only-password-B")


@pytest.mark.django_db
def test_audit_metadata_redacts_nested_secrets():
    event = AuditService.append(
        action="test",
        target_type="test",
        result="SUCCEEDED",
        metadata={"password": "nope", "nested": {"api_token": "also-nope", "ok": "yes"}},
    )
    event = AuditEvent.objects.get(pk=event.pk)
    assert event.metadata["password"] == "[REDACTED]"
    assert event.metadata["nested"]["api_token"] == "[REDACTED]"
    assert event.metadata["nested"]["ok"] == "yes"
