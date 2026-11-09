from __future__ import annotations

import hashlib
import hmac
import io
import ipaddress
import json
import re
import shlex
import time
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from common.errors import DomainError
from providers.base import FirewallRule, ResourceRef
from providers.registry import build_write_provider

_ARTIFACT_LIMIT = 128 * 1024 * 1024
_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,179}$")
_HEX_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SSH_PROBE = r"""
import json, secrets, socket, subprocess, sys, time

request = json.load(sys.stdin)
xray = "/usr/local/bin/xray"
server_port = int(request["server_port"])
target_port = int(request["target_port"])
method = request["method"]
password = request["password"]

def exact(sock, size):
    data = b""
    while len(data) < size:
        part = sock.recv(size - len(data))
        if not part:
            raise OSError("connection closed")
        data += part
    return data

def reserve_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]

def target_has_ssh_banner():
    try:
        with socket.create_connection(("127.0.0.1", target_port), timeout=3) as target:
            target.settimeout(3)
            return target.recv(256).startswith(b"SSH-2.0-")
    except OSError:
        return False

def run_probe(secret):
    socks_port = reserve_port()
    config = {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "tag": "health-socks",
            "listen": "127.0.0.1",
            "port": socks_port,
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": False},
        }],
        "outbounds": [{
            "tag": "health-shadowsocks",
            "protocol": "shadowsocks",
            "settings": {"servers": [{
                "address": "127.0.0.1",
                "port": server_port,
                "method": method,
                "password": secret,
            }]},
        }],
    }
    process = subprocess.Popen(
        [xray, "run", "-format", "json", "-config", "/dev/stdin"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        process.stdin.write(json.dumps(config, separators=(",", ":")).encode())
        process.stdin.close()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return False
            try:
                with socket.create_connection(("127.0.0.1", socks_port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            return False

        with socket.create_connection(("127.0.0.1", socks_port), timeout=4) as client:
            client.settimeout(3)
            client.sendall(b"\x05\x01\x00")
            if exact(client, 2) != b"\x05\x00":
                return False
            client.sendall(b"\x05\x01\x00\x01\x7f\x00\x00\x01" + target_port.to_bytes(2, "big"))
            reply = exact(client, 4)
            address_length = {1: 4, 4: 16}.get(reply[3])
            if reply[3] == 3:
                address_length = exact(client, 1)[0]
            if address_length is None:
                return False
            exact(client, address_length + 2)
            if reply[1] != 0:
                return False
            banner = b""
            while b"\n" not in banner and len(banner) < 256:
                part = client.recv(256 - len(banner))
                if not part:
                    break
                banner += part
            accepted = banner.startswith(b"SSH-2.0-")
            return accepted
    except (OSError, ValueError, KeyError, TypeError):
        return False
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

positive_control = target_has_ssh_banner()
accepted = run_probe(password)
rejected_invalid = not run_probe(secrets.token_urlsafe(24)) if accepted else False
print(json.dumps({
    "accepted": accepted,
    "positive_control": positive_control,
    "fresh_connection": accepted and rejected_invalid,
}, separators=(",", ":")))
"""


def _rule_key(rule: FirewallRule) -> tuple[str, int | None, int | None, str, str, int]:
    if not isinstance(rule, FirewallRule):
        raise DomainError(
            "BOOTSTRAP_FIREWALL_SNAPSHOT_INVALID",
            "防火墙读回规则格式无效",
            status_code=409,
        )
    if (
        rule.protocol not in {"tcp", "udp", "icmp", "all"}
        or not isinstance(rule.source, str)
        or not rule.source
        or rule.source_kind not in {"cidr", "provider_alias"}
        or rule.family not in {4, 6}
        or any(
            port is not None
            and (isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535)
            for port in (rule.port_from, rule.port_to)
        )
        or (
            rule.port_from is not None
            and rule.port_to is not None
            and rule.port_from > rule.port_to
        )
    ):
        raise DomainError(
            "BOOTSTRAP_FIREWALL_SNAPSHOT_INVALID",
            "防火墙读回规则无法安全合并",
            status_code=409,
        )
    if rule.source_kind == "cidr":
        try:
            source = ipaddress.ip_network(rule.source, strict=False)
        except ValueError as exc:
            raise DomainError(
                "BOOTSTRAP_FIREWALL_SNAPSHOT_INVALID",
                "防火墙读回 CIDR 无效",
                status_code=409,
            ) from exc
        if source.version != rule.family:
            raise DomainError(
                "BOOTSTRAP_FIREWALL_SNAPSHOT_INVALID",
                "防火墙读回地址族与 CIDR 不匹配",
                status_code=409,
            )
    return (
        rule.protocol,
        rule.port_from,
        rule.port_to,
        rule.source,
        rule.source_kind,
        rule.family,
    )


def merge_firewall_rules(
    existing: tuple[FirewallRule, ...] | list[FirewallRule],
    required: tuple[FirewallRule | Mapping[str, object], ...]
    | list[FirewallRule | Mapping[str, object]],
    *,
    address_families: set[int] | frozenset[int] = frozenset({4}),
) -> tuple[FirewallRule, ...]:
    """Keep the snapshot and add required ports for the node's public families."""
    if not address_families or not address_families.issubset({4, 6}):
        raise DomainError(
            "BOOTSTRAP_FIREWALL_SNAPSHOT_INVALID",
            "节点地址族无法安全确认",
            status_code=409,
        )
    existing = tuple(existing)
    validated_existing = tuple((_rule_key(rule), rule) for rule in existing)
    if not any(
        rule.protocol in {"tcp", "all"}
        and (
            (rule.port_from is None and rule.port_to is None)
            or (
                rule.port_from is not None
                and rule.port_to is not None
                and rule.port_from <= 22 <= rule.port_to
            )
        )
        for _key, rule in validated_existing
    ):
        raise DomainError(
            "BOOTSTRAP_SSH_FIREWALL_RULE_REQUIRED",
            "当前防火墙规则未确认 TCP/22 SSH 入口，拒绝替换完整规则集",
            status_code=409,
        )
    normalized = []
    for rule in required:
        if isinstance(rule, FirewallRule):
            protocol = rule.protocol
            port_from = rule.port_from
            port_to = rule.port_to
            if (
                protocol not in {"tcp", "udp"}
                or port_from is None
                or port_to is None
                or port_from != port_to
                or not 1 <= port_from <= 65535
            ):
                raise DomainError(
                    "BOOTSTRAP_FIREWALL_SNAPSHOT_INVALID",
                    "必需防火墙规则无法安全转换",
                    status_code=409,
                )
            rules = ((protocol, port_from),)
        else:
            if not isinstance(rule, Mapping):
                raise DomainError(
                    "BOOTSTRAP_FIREWALL_SNAPSHOT_INVALID",
                    "必需防火墙规则格式无效",
                    status_code=409,
                )
            protocol = rule.get("protocol")
            port = rule.get("port")
            if (
                protocol not in {"tcp", "udp"}
                or isinstance(port, bool)
                or not isinstance(port, int)
                or not 1 <= port <= 65535
            ):
                raise DomainError(
                    "BOOTSTRAP_FIREWALL_SNAPSHOT_INVALID",
                    "必需防火墙规则无法安全转换",
                    status_code=409,
                )
            rules = ((protocol, port),)
        for family in address_families:
            source = "0.0.0.0/0" if family == 4 else "::/0"
            normalized.extend(
                FirewallRule(protocol, port, port, source, "cidr", family)
                for protocol, port in rules
            )

    by_key = {key: rule for key, rule in validated_existing}
    for rule in normalized:
        by_key[_rule_key(rule)] = rule
    return tuple(
        by_key[key]
        for key in sorted(by_key, key=lambda value: tuple(str(x) for x in value))
    )


def firewall_rules_match(
    expected: tuple[FirewallRule, ...] | list[FirewallRule],
    actual: tuple[FirewallRule, ...] | list[FirewallRule],
) -> bool:
    try:
        return {_rule_key(rule) for rule in expected} == {_rule_key(rule) for rule in actual}
    except DomainError:
        return False


def download_pinned_bundle(
    artifact: dict,
    *,
    opener=urlopen,
    max_bytes: int = _ARTIFACT_LIMIT,
) -> bytes:
    """Fetch only a bounded HTTPS GitHub artifact whose pinned digest matches."""
    filename = artifact.get("filename") if isinstance(artifact, dict) else None
    url = artifact.get("url") if isinstance(artifact, dict) else None
    digest = artifact.get("sha256") if isinstance(artifact, dict) else None
    try:
        parsed = urlsplit(url or "")
    except ValueError:
        parsed = None
    if (
        not isinstance(filename, str)
        or not _FILENAME_RE.fullmatch(filename)
        or not isinstance(url, str)
        or parsed is None
        or parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or not isinstance(digest, str)
        or not _HEX_SHA256_RE.fullmatch(digest)
        or isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or max_bytes < 1
    ):
        raise DomainError(
            "BOOTSTRAP_ARTIFACT_URL_INVALID",
            "固定安装包地址或清单无效",
            status_code=503,
        )

    request = Request(url, headers={"User-Agent": "X-ray-node-bootstrap/0.14.5"})
    try:
        with opener(request, timeout=30) as response:
            final_url = urlsplit(response.geturl())
            if final_url.scheme != "https" or final_url.hostname not in {
                "github.com",
                "release-assets.githubusercontent.com",
                "objects.githubusercontent.com",
            }:
                raise DomainError(
                    "BOOTSTRAP_ARTIFACT_URL_INVALID",
                    "固定安装包重定向地址不受信任",
                    status_code=503,
                )
            content_length = getattr(response, "headers", {}).get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                raise DomainError(
                    "BOOTSTRAP_ARTIFACT_TOO_LARGE",
                    "固定安装包超过允许大小",
                    status_code=503,
                )
            body = response.read(max_bytes + 1)
    except DomainError:
        raise
    except Exception:
        raise DomainError(
            "BOOTSTRAP_ARTIFACT_DOWNLOAD_FAILED",
            "固定安装包下载失败",
            status_code=503,
        ) from None
    if len(body) > max_bytes:
        raise DomainError(
            "BOOTSTRAP_ARTIFACT_TOO_LARGE",
            "固定安装包超过允许大小",
            status_code=503,
        )
    if not hmac.compare_digest(hashlib.sha256(body).hexdigest(), digest):
        raise DomainError(
            "BOOTSTRAP_ARTIFACT_HASH_MISMATCH",
            "固定安装包 SHA-256 校验失败",
            status_code=503,
        )
    return body


def _ssh_transport(node):
    from apps.nodes.ssh import HostKeyService, sha256_fingerprint
    from apps.subscriptions.node_agent import aws_transport

    access = aws_transport(node)
    connection = None
    try:
        import paramiko

        connection = paramiko.Transport((access.host, access.port))
        connection.banner_timeout = access.timeout
        connection.auth_timeout = access.timeout
        connection.start_client(timeout=access.timeout)
        HostKeyService().verify_provider_attested(
            node.pk,
            sha256_fingerprint(connection.get_remote_server_key()),
            attested_fingerprints=access.attested_fingerprints,
            source=access.host_key_attestation_source,
        )
        connection.auth_publickey(access.username, access._authentication_key(paramiko))
        if not connection.is_authenticated():
            raise DomainError(
                "SSH_AUTHENTICATION_FAILED", "SSH 身份验证失败", status_code=403
            )
        return connection
    except DomainError:
        if connection is not None:
            connection.close()
        raise
    except Exception:
        if connection is not None:
            connection.close()
        raise DomainError("SSH_UNAVAILABLE", "节点 SSH 连接不可用", status_code=503) from None


def _exec(
    connection, command: str, *, payload: bytes = b"", timeout: int = 60
) -> tuple[int, bytes]:
    channel = connection.open_session(timeout=15)
    channel.settimeout(1)
    channel.exec_command(command)
    if payload:
        channel.sendall(payload)
    channel.shutdown_write()
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        while not channel.exit_status_ready():
            if time.monotonic() >= deadline:
                raise DomainError(
                    "BOOTSTRAP_REMOTE_TIMEOUT", "节点远程步骤超时", status_code=504
                )
            try:
                if channel.recv_ready():
                    output.extend(channel.recv(4096))
                if channel.recv_stderr_ready():
                    channel.recv_stderr(4096)
            except TimeoutError:
                pass
            if len(output) > 65536:
                raise DomainError(
                    "BOOTSTRAP_REMOTE_OUTPUT_TOO_LARGE",
                    "节点远程步骤输出超过限制",
                    status_code=502,
                )
            time.sleep(0.02)
        while channel.recv_ready():
            output.extend(channel.recv(4096))
            if len(output) > 65536:
                raise DomainError(
                    "BOOTSTRAP_REMOTE_OUTPUT_TOO_LARGE",
                    "节点远程步骤输出超过限制",
                    status_code=502,
                )
        return channel.recv_exit_status(), bytes(output)
    finally:
        channel.close()


class NodeBootstrapRuntime:
    def transport_factory(self, node):
        from apps.subscriptions.node_agent import aws_transport

        return aws_transport(node)

    def install(self, node, manifest, *, operation_id, claim):
        if node.cloud_account.provider != "aws_lightsail":
            raise DomainError(
                "BOOTSTRAP_PROVIDER_UNSUPPORTED",
                "当前初始化运行时只支持 AWS Lightsail",
                status_code=409,
            )
        connection = _ssh_transport(node)
        stage = f"/tmp/xray-bootstrap-{uuid4().hex}"
        sftp = None
        try:
            status, platform_output = _exec(
                connection, "uname -s; uname -m", timeout=15
            )
            if status != 0:
                raise DomainError(
                    "BOOTSTRAP_PLATFORM_UNKNOWN", "无法确认节点系统架构", status_code=409
                )
            values = platform_output.decode("ascii", "ignore").splitlines()
            if len(values) != 2 or values[0].strip().lower() != "linux":
                raise DomainError(
                    "BOOTSTRAP_PLATFORM_UNSUPPORTED", "节点不是受支持的 Linux 系统", status_code=409
                )
            machine = values[1].strip().lower()
            platform = {
                "x86_64": "linux-amd64",
                "amd64": "linux-amd64",
                "aarch64": "linux-arm64",
                "arm64": "linux-arm64",
            }.get(machine)
            if platform is None:
                raise DomainError(
                    "BOOTSTRAP_PLATFORM_UNSUPPORTED", "节点 CPU 架构不受支持", status_code=409
                )
            artifact = manifest["artifacts"].get(platform)
            if not isinstance(artifact, dict):
                raise DomainError(
                    "BOOTSTRAP_ARTIFACT_UNAVAILABLE", "固定架构安装包不可用", status_code=503
                )
            archive = download_pinned_bundle(artifact)

            root = Path(__file__).resolve().parents[3] / "installer"
            relative_files = (
                "manifest.json",
                "install.sh",
                "verify.sh",
                "apply-config.sh",
                "inline-certificates.py",
                "xray.service",
                "licenses/MPL-2.0.txt",
            )
            safe_stage = shlex.quote(stage)
            status, _ = _exec(
                connection,
                "umask 077; mkdir -m 700 "
                + safe_stage
                + "; mkdir -m 700 "
                + safe_stage
                + "/licenses",
                timeout=15,
            )
            if status != 0:
                raise DomainError(
                    "BOOTSTRAP_STAGING_FAILED", "无法准备节点临时安装目录", status_code=409
                )
            sftp = __import__("paramiko").SFTPClient.from_transport(connection)
            for relative in relative_files:
                local_path = root / relative
                remote_path = f"{stage}/{relative}"
                sftp.put(str(local_path), remote_path)
                sftp.chmod(remote_path, 0o600)
            archive_path = f"{stage}/{artifact['filename']}"
            sftp.putfo(io.BytesIO(archive), archive_path)
            sftp.chmod(archive_path, 0o600)

            status, _ = _exec(
                connection,
                "sudo -n sh -c 'command -v jq >/dev/null && command -v unzip >/dev/null'",
                timeout=20,
            )
            if status != 0:
                status, _ = _exec(
                    connection,
                    "sudo -n env DEBIAN_FRONTEND=noninteractive apt-get update -qq && "
                    "sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq jq unzip",
                    timeout=300,
                )
                if status != 0:
                    raise DomainError(
                        "BOOTSTRAP_DEPENDENCIES_UNAVAILABLE",
                        "节点安装依赖未能准备",
                        status_code=409,
                    )

            install_command = (
                "sudo -n bash "
                + shlex.quote(f"{stage}/install.sh")
                + " "
                + shlex.quote(archive_path)
            )
            status, output = _exec(connection, install_command, timeout=600)
            if status != 0 or not _successful_installer_output(output, manifest, platform):
                raise DomainError(
                    "BOOTSTRAP_INSTALLER_FAILED", "固定版本节点安装失败或无法验证", status_code=409
                )
            status, output = _exec(
                connection,
                "sudo -n bash " + shlex.quote(f"{stage}/verify.sh"),
                timeout=30,
            )
            if status != 0 or not _successful_verifier_output(output, manifest):
                raise DomainError(
                    "BOOTSTRAP_INSTALLER_UNVERIFIED",
                    "节点安装后读回验证失败",
                    status_code=409,
                )
            return {
                "verified": True,
                "platform": platform,
                "installer_version": manifest["installer_version"],
                "xray_version": manifest["xray_version"],
                "bundle_hash": artifact["sha256"],
            }
        finally:
            if sftp is not None:
                sftp.close()
            try:
                _exec(
                    connection,
                    "sudo -n rm -rf -- " + shlex.quote(stage),
                    timeout=15,
                )
            except Exception:
                pass
            connection.close()

    def configure_firewall(self, node, required_rules, *, operation_id, claim):
        from apps.nodes.lifecycle import NodeLifecycle
        from apps.operations.authorization import DatabaseWriteAuthorizer
        from apps.operations.models import Operation

        operation = Operation.objects.get(pk=operation_id)
        if (
            operation.target_id != node.pk
            or operation.cloud_credential_version_id != node.cloud_credential_version_id
        ):
            raise DomainError(
                "OPERATION_TARGET_MISMATCH", "防火墙操作目标不匹配", status_code=409
            )
        provider = build_write_provider(
            node.cloud_account_id,
            node.region,
            authorizer=DatabaseWriteAuthorizer(claim),
            credential_version=node.cloud_credential_version.version,
        )
        resource = ResourceRef(
            NodeLifecycle._account_ref(node), node.region, node.external_id
        )
        if not isinstance(node.addresses, list):
            raise DomainError(
                "BOOTSTRAP_FIREWALL_SNAPSHOT_INVALID",
                "节点地址读回无法安全确认",
                status_code=409,
            )
        address_families = set()
        for address in node.addresses:
            family = address.get("family") if isinstance(address, dict) else None
            if family not in {4, 6} or isinstance(family, bool):
                raise DomainError(
                    "BOOTSTRAP_FIREWALL_SNAPSHOT_INVALID",
                    "节点地址族无法安全确认",
                    status_code=409,
                )
            address_families.add(family)
        if 4 not in address_families:
            raise DomainError(
                "BOOTSTRAP_FIREWALL_SNAPSHOT_INVALID",
                "节点 IPv4 地址尚未读回",
                status_code=409,
            )
        before = provider.get_firewall(resource)
        merged = merge_firewall_rules(
            before.rules, required_rules, address_families=address_families
        )
        permit = NodeLifecycle._permit(
            node, operation, claim, "firewall", resource_id=node.external_id
        )
        mutation = provider.configure_firewall(resource, merged, permit=permit)
        after = provider.get_firewall(resource)
        return {
            "read_before_write": True,
            "write_confirmed": mutation.outcome in {"accepted", "completed"},
            "read_after_write": True,
            "rules_verified": firewall_rules_match(merged, after.rules),
        }

    def health_probe(self, node):
        from apps.nodes.bootstrap import _active_subscription_profile_ids
        from apps.nodes.models import NodeProtocol
        from apps.subscriptions.credentials import decrypt_material
        from apps.subscriptions.models import NodeCredential

        if node.cloud_account.provider != "aws_lightsail":
            return {"accepted": False, "positive_control": False, "fresh_connection": False}
        profile_ids = _active_subscription_profile_ids()
        if not profile_ids:
            return {"accepted": False, "positive_control": False, "fresh_connection": False}
        protocol = NodeProtocol.objects.filter(
            node=node,
            protocol="shadowsocks",
            port=8388,
            enabled=True,
            method="aes-128-gcm",
        ).first()
        if protocol is None:
            return {"accepted": False, "positive_control": False, "fresh_connection": False}
        credential = (
            NodeCredential.objects.filter(
                node=node,
                protocol=protocol,
                profile_id__in=profile_ids,
                revoked_at__isnull=True,
                desired_generation=node.applied_generation,
                applied_generation=node.applied_generation,
            )
            .select_related("profile")
            .order_by("profile_id", "-version")
            .first()
        )
        if credential is None:
            return {"accepted": False, "positive_control": False, "fresh_connection": False}
        material = decrypt_material(credential)
        password = material.get("password")
        if not isinstance(password, str) or not password:
            return {"accepted": False, "positive_control": False, "fresh_connection": False}

        connection = _ssh_transport(node)
        try:
            command = "python3 -c " + shlex.quote(_SSH_PROBE)
            payload = json.dumps(
                {
                    "server_port": protocol.port,
                    "target_port": 22,
                    "method": protocol.method,
                    "password": password,
                },
                separators=(",", ":"),
            ).encode()
            status, output = _exec(connection, command, payload=payload, timeout=30)
            if status != 0:
                return {"accepted": False, "positive_control": False, "fresh_connection": False}
            result = json.loads(output.decode("utf-8"))
            return {
                key: result.get(key) is True
                for key in ("accepted", "positive_control", "fresh_connection")
            }
        except Exception:
            return {"accepted": False, "positive_control": False, "fresh_connection": False}
        finally:
            connection.close()


def _successful_installer_output(output: bytes, manifest: dict, platform: str) -> bool:
    try:
        result = json.loads(output.decode("utf-8").strip().splitlines()[-1])
    except (UnicodeDecodeError, json.JSONDecodeError, IndexError):
        return False
    return (
        result.get("ok") is True
        and result.get("verified") is True
        and result.get("platform") == platform
        and result.get("xray_version") == manifest.get("xray_version")
    )


def _successful_verifier_output(output: bytes, manifest: dict) -> bool:
    try:
        result = json.loads(output.decode("utf-8").strip().splitlines()[-1])
    except (UnicodeDecodeError, json.JSONDecodeError, IndexError):
        return False
    return result.get("ok") is True and result.get("xray_version") == manifest.get("xray_version")


def health_probe(node):
    return NodeBootstrapRuntime().health_probe(node)
