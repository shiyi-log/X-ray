from unittest.mock import Mock

import pytest
from cryptography.exceptions import InvalidTag
from django.utils import timezone as django_timezone

from apps.cloud_accounts.services import create_account, rotate_credentials
from common.crypto import configured_secret_store
from common.errors import DomainError
from providers.base import AccountIdentity, SecretInput


@pytest.fixture
def fake_reader(monkeypatch):
    reader = Mock()
    reader.validate_credentials.return_value = AccountIdentity(
        "aws_lightsail", "111111111111", "principal-1", django_timezone.now()
    )
    monkeypatch.setattr(
        "apps.cloud_accounts.services.reader_for_input", lambda credentials, region: reader
    )
    return reader


@pytest.mark.django_db
def test_create_and_rotate_retain_old_encrypted_version(fake_reader):
    account = create_account(
        name="test",
        credentials=SecretInput(
            "aws_lightsail",
            {"access_key_id": "TEST-A", "secret_access_key": "TEST-B"},
        ),
        region="ap-northeast-1",
    )
    old = account.credential_versions.get(version=1).encrypted_credentials
    fake_reader.validate_credentials.return_value = AccountIdentity(
        "aws_lightsail", "111111111111", "principal-2", django_timezone.now()
    )
    rotated = rotate_credentials(
        account.pk,
        credentials=SecretInput(
            "aws_lightsail",
            {"access_key_id": "TEST-C", "secret_access_key": "TEST-D"},
        ),
        region="ap-northeast-1",
        expected_version=1,
    )
    assert rotated.credential_version == 2
    assert rotated.credential_versions.count() == 2
    assert rotated.credential_versions.get(version=1).encrypted_credentials == old


@pytest.mark.django_db
def test_rotation_cannot_change_cloud_identity(fake_reader):
    account = create_account(
        name="test",
        credentials=SecretInput("aws_lightsail", {"access_key_id": "A", "secret_access_key": "B"}),
        region="ap-northeast-1",
    )
    original = account.credential_versions.get(version=1)
    fake_reader.validate_credentials.return_value = AccountIdentity(
        "aws_lightsail", "222222222222", "different", django_timezone.now()
    )
    with pytest.raises(DomainError) as caught:
        rotate_credentials(
            account.pk,
            credentials=SecretInput(
                "aws_lightsail", {"access_key_id": "C", "secret_access_key": "D"}
            ),
            region="ap-northeast-1",
        )
    assert caught.value.code == "CLOUD_IDENTITY_MISMATCH"
    account.refresh_from_db()
    original.refresh_from_db()
    assert account.credential_version == 1
    assert account.credential_versions.count() == 1
    assert original.encrypted_credentials


@pytest.mark.django_db
def test_credential_ciphertext_is_bound_to_account_and_version(fake_reader):
    first = create_account(
        name="first",
        credentials=SecretInput("aws_lightsail", {"access_key_id": "A", "secret_access_key": "B"}),
        region="ap-northeast-1",
    )
    fake_reader.validate_credentials.return_value = AccountIdentity(
        "aws_lightsail", "222222222222", "principal-2", django_timezone.now()
    )
    second = create_account(
        name="second",
        credentials=SecretInput("aws_lightsail", {"access_key_id": "C", "secret_access_key": "D"}),
        region="ap-northeast-1",
    )
    envelope = first.credential_versions.get(version=1).encrypted_credentials
    with pytest.raises(InvalidTag):
        configured_secret_store().decrypt(
            envelope,
            purpose="control.cloud_credentials",
            aad=f"cloud-account:{second.pk}:credentials:1".encode(),
        )


@pytest.mark.django_db
def test_credential_version_is_immutable(fake_reader):
    account = create_account(
        name="test",
        credentials=SecretInput("aws_lightsail", {"access_key_id": "A", "secret_access_key": "B"}),
        region="ap-northeast-1",
    )
    record = account.credential_versions.get(version=1)
    record.encrypted_credentials = {"changed": True}
    with pytest.raises(Exception):
        record.save()
