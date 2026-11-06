from __future__ import annotations

import base64
import hashlib
import io
import json
import re

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.db import transaction
from django.utils import timezone

from common.errors import DomainError

from .models import HostKeyRecord, ManagedNode


def valid_sha256_fingerprint(fingerprint: str) -> bool:
    if not isinstance(fingerprint, str) or not re.fullmatch(
        r"SHA256:[A-Za-z0-9+/]{43}", fingerprint
    ):
        return False
    try:
        return len(base64.b64decode(fingerprint[7:] + "=", validate=True)) == 32
    except (ValueError, base64.binascii.Error):
        return False


class HostKeyService:
    def observe(self, node_id, fingerprint: str, *, source: str) -> HostKeyRecord:
        fingerprint = fingerprint.strip()
        if not valid_sha256_fingerprint(fingerprint):
            raise DomainError("SSH_FINGERPRINT_INVALID", "SSH 指纹格式无效", status_code=400)
        node = ManagedNode.objects.get(pk=node_id)
        approved = node.host_keys.filter(status="APPROVED").first()
        status = "REJECTED" if approved and approved.fingerprint != fingerprint else "CANDIDATE"
        record, _created = HostKeyRecord.objects.get_or_create(
            node=node,
            fingerprint=fingerprint,
            defaults={"source": source[:80], "status": status},
        )
        return record

    def approve(
        self,
        record_id,
        *,
        expected_fingerprint: str,
        source: str,
    ) -> HostKeyRecord:
        with transaction.atomic():
            record = HostKeyRecord.objects.select_for_update().get(pk=record_id)
            if record.fingerprint != expected_fingerprint:
                raise DomainError(
                    "SSH_FINGERPRINT_CONFIRMATION_MISMATCH",
                    "确认的 SSH 指纹不匹配",
                    status_code=409,
                )
            HostKeyRecord.objects.filter(node=record.node, status="APPROVED").exclude(
                pk=record.pk
            ).update(status="SUPERSEDED")
            record.status = "APPROVED"
            record.source = source[:80]
            record.approved_at = timezone.now()
            record.save(update_fields=["status", "source", "approved_at"])
            return record

    def verify(self, node_id, fingerprint: str) -> HostKeyRecord:
        approved = HostKeyRecord.objects.filter(node_id=node_id, status="APPROVED").first()
        if approved is None:
            self.observe(node_id, fingerprint, source="ssh-handshake")
            raise DomainError(
                "SSH_HOST_KEY_NOT_APPROVED", "SSH 主机指纹尚未批准", status_code=409
            )
        if approved.fingerprint != fingerprint:
            HostKeyRecord.objects.get_or_create(
                node_id=node_id,
                fingerprint=fingerprint,
                defaults={"source": "ssh-handshake", "status": "REJECTED"},
            )
            raise DomainError("SSH_HOST_KEY_CHANGED", "SSH 主机指纹已变化", status_code=409)
        return approved

    def verify_provider_attested(
        self,
        node_id,
        fingerprint: str,
        *,
        attested_fingerprints,
        source: str,
    ) -> HostKeyRecord:
        fingerprint = fingerprint.strip()
        if not valid_sha256_fingerprint(fingerprint):
            raise DomainError("SSH_FINGERPRINT_INVALID", "SSH 指纹格式无效", status_code=400)
        attested = {
            value
            for value in (attested_fingerprints or ())
            if valid_sha256_fingerprint(value)
        }
        failure_code = ""
        record = None
        with transaction.atomic():
            ManagedNode.objects.select_for_update().only("pk").get(pk=node_id)
            approved = (
                HostKeyRecord.objects.select_for_update()
                .filter(node_id=node_id, status="APPROVED")
                .order_by("-approved_at", "-created_at")
                .first()
            )
            if approved is not None and approved.fingerprint != fingerprint:
                record, created = HostKeyRecord.objects.get_or_create(
                    node_id=node_id,
                    fingerprint=fingerprint,
                    defaults={"source": source[:80], "status": "REJECTED"},
                )
                if not created and record.status != "REJECTED":
                    record.status = "REJECTED"
                    record.source = source[:80]
                    record.save(update_fields=["status", "source"])
                failure_code = "SSH_HOST_KEY_CHANGED"
            elif approved is not None:
                record = approved
            else:
                candidate = self.observe(node_id, fingerprint, source=source)
                if fingerprint not in attested:
                    failure_code = "SSH_HOST_KEY_NOT_APPROVED"
                else:
                    record = self.approve(
                        candidate.pk,
                        expected_fingerprint=fingerprint,
                        source=source,
                    )

        if failure_code == "SSH_HOST_KEY_CHANGED":
            raise DomainError("SSH_HOST_KEY_CHANGED", "SSH 主机指纹已变化", status_code=409)
        if failure_code == "SSH_HOST_KEY_NOT_APPROVED":
            raise DomainError(
                "SSH_HOST_KEY_NOT_APPROVED", "SSH 主机指纹尚未批准", status_code=409
            )
        if record is None:
            raise DomainError("SSH_HOST_KEY_NOT_APPROVED", "SSH 主机指纹尚未批准", status_code=409)
        return record


def sha256_fingerprint(server_key) -> str:
    digest = hashlib.sha256(server_key.asbytes()).digest()
    encoded = base64.b64encode(digest).decode("ascii").rstrip("=")
    return f"SHA256:{encoded}"


class ParamikoApplyTransport:
    """Pinned-host-key SSH transport; credentials and config remain in memory/stdin."""

    def __init__(
        self,
        *,
        node_id,
        host: str,
        username: str,
        private_key: str,
        certificate: str | None = None,
        port: int = 22,
        timeout: int = 15,
        host_keys: HostKeyService | None = None,
        attested_fingerprints: tuple[str, ...] = (),
        host_key_attestation_source: str = "",
        remote_command: str = "/opt/xray-manager/apply-config.sh",
    ):
        self.node_id = node_id
        self.host = host
        self.username = username
        self.private_key = private_key
        self.certificate = certificate
        self.port = port
        self.timeout = timeout
        self.host_keys = host_keys or HostKeyService()
        self.attested_fingerprints = attested_fingerprints
        self.host_key_attestation_source = host_key_attestation_source
        self.remote_command = remote_command

    @staticmethod
    def _load_private_key(paramiko_module, value: str):
        errors = []
        for key_type in (
            paramiko_module.Ed25519Key,
            paramiko_module.RSAKey,
            paramiko_module.ECDSAKey,
        ):
            try:
                return key_type.from_private_key(io.StringIO(value))
            except Exception as exc:
                errors.append(type(exc).__name__)
        # AWS ephemeral EC keys may use PKCS#8, whose PEM header Paramiko does not accept.
        if isinstance(value, str) and value.lstrip().startswith("-----BEGIN PRIVATE KEY-----"):
            try:
                key = serialization.load_pem_private_key(value.encode("ascii"), password=None)
                if isinstance(key, ec.EllipticCurvePrivateKey) and isinstance(
                    key.curve, (ec.SECP256R1, ec.SECP384R1, ec.SECP521R1)
                ):
                    normalized = key.private_bytes(
                        serialization.Encoding.PEM,
                        serialization.PrivateFormat.TraditionalOpenSSL,
                        serialization.NoEncryption(),
                    ).decode("ascii")
                    return paramiko_module.ECDSAKey.from_private_key(io.StringIO(normalized))
            except (
                TypeError,
                ValueError,
                UnsupportedAlgorithm,
                paramiko_module.SSHException,
            ) as exc:
                errors.append(type(exc).__name__)
        raise DomainError(
            "SSH_PRIVATE_KEY_INVALID",
            "SSH 私钥格式无效",
            status_code=400,
            details={"attempted_key_types": errors},
        )

    def _authentication_key(self, paramiko_module):
        key = self._load_private_key(paramiko_module, self.private_key)
        if self.certificate is not None:
            try:
                if not isinstance(self.certificate, str):
                    raise ValueError("SSH certificate required")
                certificate = serialization.load_ssh_public_identity(
                    self.certificate.encode("ascii")
                )
                if not isinstance(certificate, serialization.SSHCertificate):
                    raise ValueError("SSH certificate required")
                public = certificate.public_key().public_bytes(
                    serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
                )
                if base64.b64decode(public.split()[1]) != key.asbytes():
                    raise ValueError("SSH certificate key mismatch")
                key.load_certificate(self.certificate)
            except (ValueError, TypeError, UnsupportedAlgorithm, paramiko_module.SSHException):
                raise DomainError(
                    "SSH_CERTIFICATE_INVALID", "SSH 证书无效或与私钥不匹配", status_code=400
                ) from None
        return key

    def apply(self, request: dict) -> dict:
        import paramiko

        transport = paramiko.Transport((self.host, self.port))
        transport.banner_timeout = self.timeout
        transport.auth_timeout = self.timeout
        try:
            transport.start_client(timeout=self.timeout)
            fingerprint = sha256_fingerprint(transport.get_remote_server_key())
            if self.host_key_attestation_source:
                self.host_keys.verify_provider_attested(
                    self.node_id,
                    fingerprint,
                    attested_fingerprints=self.attested_fingerprints,
                    source=self.host_key_attestation_source,
                )
            else:
                self.host_keys.verify(self.node_id, fingerprint)
            key = self._authentication_key(paramiko)
            try:
                transport.auth_publickey(self.username, key)
            except paramiko.AuthenticationException:
                raise DomainError(
                    "SSH_AUTHENTICATION_FAILED", "SSH 身份验证失败", status_code=403
                ) from None
            if not transport.is_authenticated():
                raise DomainError(
                    "SSH_AUTHENTICATION_FAILED", "SSH 身份验证失败", status_code=403
                )
            channel = transport.open_session(timeout=self.timeout)
            channel.settimeout(self.timeout)
            channel.exec_command(self.remote_command)
            channel.sendall(json.dumps(request, separators=(",", ":")).encode())
            channel.shutdown_write()
            stdout = channel.makefile("r").read(65536)
            channel.makefile_stderr("r").read(65536)
            exit_status = channel.recv_exit_status()
            try:
                response = json.loads(stdout)
            except (TypeError, json.JSONDecodeError) as exc:
                raise DomainError(
                    "SSH_RESPONSE_INVALID", "节点执行器响应无效", status_code=502
                ) from exc
            if exit_status != 0 or response.get("ok") is not True:
                raise DomainError(
                    str(response.get("error_code") or "REMOTE_APPLY_FAILED")[:100],
                    "节点配置应用失败",
                    status_code=409,
                    details={"exit_status": exit_status},
                )
            return response
        finally:
            transport.close()
