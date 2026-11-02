from __future__ import annotations

import json
import socket

from django.conf import settings

from apps.nodes.ssh import HostKeyService, ParamikoApplyTransport, sha256_fingerprint
from common.errors import DomainError
from providers.registry import build_read_provider


def aws_transport(node):
    """Use in-memory AWS access details and an already approved host fingerprint."""
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
        HostKeyService().verify(node.pk, sha256_fingerprint(connection.get_remote_server_key()))
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
