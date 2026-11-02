from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import paramiko
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import SSHCertificateBuilder, SSHCertificateType

from apps.nodes.ssh import ParamikoApplyTransport
from common.errors import DomainError


def credential_pair():
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(UTC)
    certificate = (
        SSHCertificateBuilder()
        .public_key(key.public_key())
        .type(SSHCertificateType.USER)
        .valid_principals([b"ubuntu"])
        .valid_after(int((now - timedelta(minutes=1)).timestamp()))
        .valid_before(int((now + timedelta(minutes=5)).timestamp()))
        .sign(ec.generate_private_key(ec.SECP256R1()))
        .public_bytes()
        .decode("ascii")
    )
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    return private, certificate


def test_certificate_is_loaded_without_changing_signing_identity():
    private, certificate = credential_pair()
    transport = ParamikoApplyTransport(
        node_id=uuid4(), host="unused", username="ubuntu", private_key=private,
        certificate=certificate,
    )
    loaded = transport._authentication_key(paramiko)
    assert loaded.can_sign()
    assert loaded.public_blob.key_type.endswith("-cert-v01@openssh.com")
    plain = ParamikoApplyTransport._load_private_key(paramiko, private)
    assert loaded.asbytes() == plain.asbytes()
    verifier = paramiko.PKey.from_type_string(
        loaded.get_name(), loaded.asbytes(),
    )
    signature = loaded.sign_ssh_data(b"certificate-authentication-regression")
    assert verifier.verify_ssh_sig(
        b"certificate-authentication-regression", paramiko.Message(signature.asbytes()),
    )


@pytest.mark.parametrize("invalid", ["mismatch", "malformed"])
def test_certificate_failure_is_safe(invalid, caplog):
    private, certificate = credential_pair()
    if invalid == "mismatch":
        _, certificate = credential_pair()
    else:
        certificate = "invalid certificate payload"
    transport = ParamikoApplyTransport(
        node_id=uuid4(), host="unused", username="ubuntu", private_key=private,
        certificate=certificate,
    )
    with pytest.raises(DomainError) as caught:
        transport._authentication_key(paramiko)
    assert caught.value.code == "SSH_CERTIFICATE_INVALID"
    rendered = str(caught.value) + repr(caught.value.details) + caplog.text
    if private in rendered or certificate in rendered:
        pytest.fail("certificate rejection exposed credential material", pytrace=False)


def test_host_key_is_verified_before_loading_authentication_material(monkeypatch):
    connection = Mock()
    connection.get_remote_server_key.return_value.asbytes.return_value = b"server-public-key"
    monkeypatch.setattr(paramiko, "Transport", Mock(return_value=connection))
    host_keys = Mock()
    host_keys.verify.side_effect = DomainError("SSH_HOST_KEY_NOT_APPROVED", "not approved")
    transport = ParamikoApplyTransport(
        node_id=uuid4(), host="unused", username="ubuntu", private_key="not-read",
        host_keys=host_keys,
    )
    loader = Mock()
    monkeypatch.setattr(transport, "_authentication_key", loader)
    with pytest.raises(DomainError):
        transport.apply({})
    loader.assert_not_called()
    connection.auth_publickey.assert_not_called()
    connection.close.assert_called_once()


def test_legacy_authentication_without_certificate():
    private, _ = credential_pair()
    transport = ParamikoApplyTransport(
        node_id=uuid4(), host="unused", username="ubuntu", private_key=private,
    )
    assert transport._authentication_key(paramiko).public_blob is None


def test_certificate_argument_cannot_read_a_local_file(tmp_path, monkeypatch):
    private, certificate = credential_pair()
    path = tmp_path / "certificate.pub"
    path.write_text(certificate)
    transport = ParamikoApplyTransport(
        node_id=uuid4(), host="unused", username="ubuntu", private_key=private,
        certificate=str(path),
    )
    key = transport._load_private_key(paramiko, private)
    reader = Mock(side_effect=AssertionError("must validate content before file-aware API"))
    monkeypatch.setattr(key, "load_certificate", reader)
    monkeypatch.setattr(transport, "_load_private_key", Mock(return_value=key))
    with pytest.raises(DomainError) as caught:
        transport._authentication_key(paramiko)
    assert caught.value.code == "SSH_CERTIFICATE_INVALID"
    reader.assert_not_called()


def test_authentication_rejection_is_redacted_and_connection_closed(monkeypatch, caplog):
    private, certificate = credential_pair()
    connection = Mock()
    connection.get_remote_server_key.return_value.asbytes.return_value = b"server-public-key"
    connection.auth_publickey.side_effect = paramiko.AuthenticationException(
        "unsafe provider text " + private,
    )
    monkeypatch.setattr(paramiko, "Transport", Mock(return_value=connection))
    transport = ParamikoApplyTransport(
        node_id=uuid4(), host="unused", username="ubuntu", private_key=private,
        certificate=certificate, host_keys=Mock(),
    )
    with pytest.raises(DomainError) as caught:
        transport.apply({})
    assert caught.value.code == "SSH_AUTHENTICATION_FAILED"
    if private in str(caught.value) + caplog.text:
        pytest.fail("authentication error exposed private key", pytrace=False)
    connection.open_session.assert_not_called()
    connection.close.assert_called_once()
