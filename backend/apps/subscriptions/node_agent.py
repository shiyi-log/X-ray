from __future__ import annotations

import base64
import hashlib
import json
import socket
from datetime import UTC, datetime

from django.conf import settings
from django.utils import timezone

from apps.nodes.ssh import (
    HostKeyService,
    ParamikoApplyTransport,
    sha256_fingerprint,
    valid_sha256_fingerprint,
)
from common.errors import DomainError
from providers.registry import build_read_provider


def _access_key_timestamp(value):
    if isinstance(value, datetime):
        return value if timezone.is_aware(value) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _provider_attested_fingerprints(access_details, *, now=None):
    now = now or timezone.now()
    fingerprints = []
    for key in access_details.get("hostKeys") or []:
        algorithm = key.get("algorithm")
        encoded_key = key.get("publicKey")
        fingerprint = key.get("fingerprintSHA256")
        witnessed_at = _access_key_timestamp(key.get("witnessedAt"))
        if (
            not isinstance(algorithm, str)
            or not isinstance(encoded_key, str)
            or not valid_sha256_fingerprint(fingerprint)
            or witnessed_at is None
            or witnessed_at > now
        ):
            continue
        try:
            key_blob = base64.b64decode(
                encoded_key + "=" * (-len(encoded_key) % 4), validate=True
            )
        except (ValueError, base64.binascii.Error):
            continue
        if len(key_blob) < 4:
            continue
        algorithm_length = int.from_bytes(key_blob[:4], "big")
        if algorithm_length < 1 or len(key_blob) < 4 + algorithm_length:
            continue
        try:
            wire_algorithm = key_blob[4 : 4 + algorithm_length].decode("ascii")
        except UnicodeDecodeError:
            continue
        if wire_algorithm != algorithm:
            continue
        actual = "SHA256:" + base64.b64encode(hashlib.sha256(key_blob).digest()).decode(
            "ascii"
        ).rstrip("=")
        if actual == fingerprint:
            fingerprints.append(fingerprint)
    return tuple(sorted(set(fingerprints)))


def aws_transport(node):
    """Use in-memory AWS credentials and provider-attested SSH host keys."""
    if node.cloud_account.provider != "aws_lightsail":
        raise DomainError(
            "NODE_EXECUTOR_UNAVAILABLE", "该云平台尚未配置 SSH 适配器", status_code=503
        )
    reader = build_read_provider(node.cloud_account_id, node.region)
    client = reader._provider.lightsail
    details = client.get_instance_access_details(instanceName=node.external_id, protocol="ssh")[
        "accessDetails"
    ]
    if details["instanceName"] != node.external_id:
        raise DomainError("RESOURCE_OWNERSHIP_MISMATCH", "SSH 目标不匹配", status_code=409)
    private_key = details["privateKey"]
    certificate = details.get("certKey")
    if getattr(settings, "XRAY_ALLOW_REGIONAL_DEFAULT_KEY", False):
        value = client.download_default_key_pair()["privateKeyBase64"]
        private_key = value.decode() if isinstance(value, bytes) else value
        certificate = None
    return ParamikoApplyTransport(
        node_id=node.pk,
        host=details["ipAddress"],
        username=details["username"],
        private_key=private_key,
        certificate=certificate,
        attested_fingerprints=_provider_attested_fingerprints(details),
        host_key_attestation_source="aws-lightsail-access-details",
        remote_command="sudo -n /opt/xray-manager/apply-config.sh",
        timeout=30,
    )


STATS_PROGRAM = """import json,subprocess,pathlib,time,datetime
before=pathlib.Path('/var/lib/xray-manager/current-generation').read_text().strip()
r=subprocess.run(['/usr/local/bin/xray','api','statsquery','--server=127.0.0.1:10085','-pattern','user>>>'],capture_output=True,timeout=10)
assert r.returncode==0
result=json.loads(r.stdout)
process=subprocess.run(['systemctl','show','xray','--property=ExecMainStartTimestampMonotonic','--value'],capture_output=True,timeout=5)
assert process.returncode==0
after=pathlib.Path('/var/lib/xray-manager/current-generation').read_text().strip()
assert before==after
result.update(generation=int(after),boot_id=pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),process_id=process.stdout.decode().strip(),sequence=time.monotonic_ns(),sampled_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
print(json.dumps(result))
"""


def fetch_usage(node):
    import paramiko

    transport_info = aws_transport(node)
    connection = paramiko.Transport(socket.create_connection((transport_info.host, 22), timeout=10))
    try:
        connection.banner_timeout = 10
        connection.auth_timeout = 15
        connection.start_client(timeout=10)
        HostKeyService().verify_provider_attested(
            node.pk,
            sha256_fingerprint(connection.get_remote_server_key()),
            attested_fingerprints=transport_info.attested_fingerprints,
            source=transport_info.host_key_attestation_source,
        )
        connection.auth_publickey(
            transport_info.username, transport_info._authentication_key(paramiko)
        )
        channel = connection.open_session(timeout=10)
        channel.settimeout(20)
        channel.exec_command("sudo -n python3 -")
        channel.sendall(STATS_PROGRAM.encode())
        channel.shutdown_write()
        raw = channel.makefile("rb").read(1024 * 1024)
        channel.makefile_stderr("rb").read(4096)
        if channel.recv_exit_status() != 0:
            raise DomainError("USAGE_COLLECTOR_UNAVAILABLE", "节点统计接口不可用", status_code=503)
        return json.loads(raw)
    finally:
        connection.close()
