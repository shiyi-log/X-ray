import base64
import hashlib
import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

_PURPOSES = {"control", "subscription"}


def _purpose_domain(purpose: str) -> str:
    domain = purpose.split(".", 1)[0]
    if domain not in _PURPOSES:
        raise ValueError("unsupported purpose")
    return domain


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


class SecretStore:
    """Envelope encryption with per-record DEKs and purpose/AAD binding.

    ``master_keys`` maps purpose to ``{version: raw_32_byte_key}``; callers may
    retain old versions to decrypt during rotation, while encrypt always uses
    the highest version.
    """

    def __init__(self, master_keys):
        self.master_keys = {p: dict(v) for p, v in master_keys.items()}
        unknown = set(self.master_keys) - _PURPOSES
        if unknown:
            raise ValueError(f"unsupported purpose: {sorted(unknown)}")
        for versions in self.master_keys.values():
            for key in versions.values():
                if len(key) != 32:
                    raise ValueError("master keys must be 32 bytes")

    def _aad(self, purpose, key_version, aad):
        _purpose_domain(purpose)
        return (
            b"xray-envelope/v1|" + purpose.encode() + b"|" + str(key_version).encode() + b"|" + aad
        )

    def encrypt(self, plaintext: bytes, *, purpose: str, aad: bytes = b"") -> dict:
        domain = _purpose_domain(purpose)
        if domain not in self.master_keys or not self.master_keys[domain]:
            raise ValueError("unsupported purpose")
        version = max(self.master_keys[domain])
        master = self.master_keys[domain][version]
        dek = AESGCM.generate_key(bit_length=256)
        nonce = secrets.token_bytes(12)
        wrapped_nonce = secrets.token_bytes(12)
        context = self._aad(purpose, version, aad)
        ciphertext = AESGCM(dek).encrypt(nonce, plaintext, context)
        wrapped = AESGCM(master).encrypt(wrapped_nonce, dek, context)
        return {
            "v": 1,
            "purpose": purpose,
            "key_version": version,
            "wrapped_dek_nonce": _b64(wrapped_nonce),
            "wrapped_dek": _b64(wrapped),
            "nonce": _b64(nonce),
            "ciphertext": _b64(ciphertext),
        }

    def decrypt(self, envelope: dict, *, purpose: str, aad: bytes = b"") -> bytes:
        if envelope.get("purpose") != purpose:
            raise ValueError("purpose mismatch")
        domain = _purpose_domain(purpose)
        version = int(envelope["key_version"])
        master = self.master_keys.get(domain, {}).get(version)
        if master is None:
            raise ValueError("unknown key version")
        context = self._aad(purpose, version, aad)
        try:
            dek = AESGCM(master).decrypt(
                _unb64(envelope["wrapped_dek_nonce"]),
                _unb64(envelope["wrapped_dek"]),
                context,
            )
            return AESGCM(dek).decrypt(
                _unb64(envelope["nonce"]), _unb64(envelope["ciphertext"]), context
            )
        except InvalidTag as exc:
            raise ValueError("authentication failed") from exc


def _configured_key(name: str, *, allow_development_fallback: bool) -> bytes:
    value = os.getenv(name, "")
    if value:
        try:
            decoded = base64.urlsafe_b64decode(value.encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            decoded = b""
        if len(decoded) == 32:
            return decoded
        if len(value.encode("utf-8")) == 32:
            return value.encode("utf-8")
        raise ValueError(f"{name} must contain a 32-byte raw or base64url key")
    if not allow_development_fallback:
        raise RuntimeError(f"{name} is required")
    return hashlib.sha256((settings.SECRET_KEY + ":" + name).encode("utf-8")).digest()


def configured_secret_store(*, allow_development_fallback: bool | None = None) -> SecretStore:
    """Build the process-local store without reading cloud/provider credentials."""
    if allow_development_fallback is None:
        allow_development_fallback = getattr(settings, "DEBUG", False) or getattr(
            settings, "XRAY_ENV", ""
        ) in {"test", "development"}
    return SecretStore(
        {
            "control": {
                1: _configured_key(
                    "XRAY_CONTROL_MASTER_KEY", allow_development_fallback=allow_development_fallback
                )
            },
            "subscription": {
                1: _configured_key(
                    "XRAY_SUBSCRIPTION_MASTER_KEY",
                    allow_development_fallback=allow_development_fallback,
                )
            },
        }
    )


def configured_subscription_store(
    *, allow_development_fallback: bool | None = None
) -> SecretStore:
    """Build the public-process store without loading any control-plane key."""
    if allow_development_fallback is None:
        allow_development_fallback = getattr(settings, "DEBUG", False) or getattr(
            settings, "XRAY_ENV", ""
        ) in {"test", "development"}
    return SecretStore(
        {
            "subscription": {
                1: _configured_key(
                    "XRAY_SUBSCRIPTION_MASTER_KEY",
                    allow_development_fallback=allow_development_fallback,
                )
            }
        }
    )
