import base64
import socket

import paramiko
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

from apps.nodes.ssh import ParamikoApplyTransport
from common.errors import DomainError


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def denied(*_args, **_kwargs):
        pytest.fail("private-key parsing must not open a network connection", pytrace=False)

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def serialize(key, format_, encryption=None):
    return key.private_bytes(
        serialization.Encoding.PEM,
        format_,
        encryption or serialization.NoEncryption(),
    ).decode("ascii")


def assert_same_signing_identity(original, loaded):
    public = original.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    )
    public_blob = base64.b64decode(public.split()[1])
    assert loaded.asbytes() == public_blob
    assert loaded.can_sign() is True
    message = b"xray-private-key-parser-regression"
    signature = loaded.sign_ssh_data(message)
    verifier = paramiko.PKey.from_type_string(public.split()[0].decode("ascii"), public_blob)
    assert verifier.verify_ssh_sig(message, paramiko.Message(signature.asbytes())) is True


@pytest.mark.parametrize("curve", [ec.SECP256R1, ec.SECP384R1, ec.SECP521R1])
def test_pkcs8_ec_preserves_public_identity_and_can_sign(curve):
    key = ec.generate_private_key(curve())
    value = serialize(key, serialization.PrivateFormat.PKCS8)

    loaded = ParamikoApplyTransport._load_private_key(paramiko, value)

    assert_same_signing_identity(key, loaded)


@pytest.mark.parametrize("kind", ["rsa-pem", "ec-pem", "ed25519-openssh"])
def test_existing_private_key_formats_still_sign(kind):
    if kind == "rsa-pem":
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        format_ = serialization.PrivateFormat.TraditionalOpenSSL
    elif kind == "ec-pem":
        key = ec.generate_private_key(ec.SECP256R1())
        format_ = serialization.PrivateFormat.TraditionalOpenSSL
    else:
        key = ed25519.Ed25519PrivateKey.generate()
        format_ = serialization.PrivateFormat.OpenSSH

    loaded = ParamikoApplyTransport._load_private_key(paramiko, serialize(key, format_))

    assert_same_signing_identity(key, loaded)


@pytest.mark.parametrize("kind", ["encrypted", "damaged", "unsupported-curve", "rsa-pkcs8"])
def test_invalid_or_unsupported_pkcs8_is_safely_rejected(kind, caplog):
    if kind == "damaged":
        value = "-----BEGIN PRIVATE KEY-----\ninvalid\n-----END PRIVATE KEY-----\n"
    elif kind == "rsa-pkcs8":
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        value = serialize(key, serialization.PrivateFormat.PKCS8)
    else:
        curve = ec.SECP256K1() if kind == "unsupported-curve" else ec.SECP256R1()
        key = ec.generate_private_key(curve)
        encryption = (
            serialization.BestAvailableEncryption(b"local-test-only-passphrase")
            if kind == "encrypted"
            else None
        )
        value = serialize(key, serialization.PrivateFormat.PKCS8, encryption)

    with pytest.raises(DomainError) as caught:
        ParamikoApplyTransport._load_private_key(paramiko, value)

    error = caught.value
    assert error.code == "SSH_PRIVATE_KEY_INVALID"
    assert error.status_code == 400
    assert error.message == "SSH 私钥格式无效"
    assert all(isinstance(item, str) for item in error.details["attempted_key_types"])
    rendered = str(error) + repr(error.details) + caplog.text
    if value in rendered or "PRIVATE KEY" in rendered or "local-test-only-passphrase" in rendered:
        pytest.fail("private-key rejection exposed secret material", pytrace=False)
