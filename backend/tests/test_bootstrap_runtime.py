from __future__ import annotations

import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from django.conf import settings

from common.errors import DomainError
from providers.base import FirewallRule


def test_firewall_merge_preserves_existing_rules_and_adds_xray_ports():
    from apps.nodes.bootstrap import BOOTSTRAP_FIREWALL_RULES
    from apps.nodes.bootstrap_runtime import merge_firewall_rules

    ssh_v4 = FirewallRule("tcp", 22, 22, "192.0.2.0/24", "cidr", 4)
    ssh_v6 = FirewallRule("tcp", 22, 22, "2001:db8::/64", "cidr", 6)
    web = FirewallRule("tcp", 443, 443, "0.0.0.0/0", "cidr", 4)

    merged = merge_firewall_rules(
        (ssh_v4, ssh_v6, web), BOOTSTRAP_FIREWALL_RULES, address_families={4, 6}
    )

    required = {
        FirewallRule(protocol, port, port, "0.0.0.0/0", "cidr", 4)
        for rule in BOOTSTRAP_FIREWALL_RULES
        for protocol, port in [(rule["protocol"], rule["port"])]
    }
    required_v6 = {
        FirewallRule(protocol, port, port, "::/0", "cidr", 6)
        for rule in BOOTSTRAP_FIREWALL_RULES
        for protocol, port in [(rule["protocol"], rule["port"])]
    }
    assert {ssh_v4, ssh_v6, web, *required, *required_v6}.issubset(set(merged))
    assert len(merged) == len(set(merged))


def test_firewall_merge_does_not_open_ipv6_when_node_has_no_ipv6_address():
    from apps.nodes.bootstrap import BOOTSTRAP_FIREWALL_RULES
    from apps.nodes.bootstrap_runtime import merge_firewall_rules

    ssh_v4 = FirewallRule("tcp", 22, 22, "192.0.2.0/24", "cidr", 4)
    merged = merge_firewall_rules(
        (ssh_v4,), BOOTSTRAP_FIREWALL_RULES, address_families={4}
    )

    assert merged
    assert {rule.family for rule in merged} == {4}


def test_firewall_merge_refuses_replacement_without_existing_ssh_access():
    from apps.nodes.bootstrap import BOOTSTRAP_FIREWALL_RULES
    from apps.nodes.bootstrap_runtime import merge_firewall_rules

    with pytest.raises(DomainError, match="SSH"):
        merge_firewall_rules((), BOOTSTRAP_FIREWALL_RULES, address_families={4})


def test_test_settings_never_enable_real_node_bootstrap_or_health_probe():
    assert settings.XRAY_NODE_BOOTSTRAP_FACTORY == ""
    assert settings.XRAY_NODE_HEALTH_PROBE == ""


def test_ssh_health_probe_uses_shadowsocks_port_and_validates_fresh_proxy_connection():
    from apps.nodes.bootstrap_runtime import _SSH_PROBE

    xray = Path(
        os.getenv(
            "XRAY_TEST_BINARY",
            Path(__file__).resolve().parents[2] / "runtime/xray/v26.3.27/xray",
        )
    )
    if not xray.is_file() or not os.access(xray, os.X_OK):
        pytest.skip("fixed Xray test binary is unavailable")

    def reserve_port():
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            return listener.getsockname()[1]

    server_port = reserve_port()
    target = socket.socket()
    target.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    target.bind(("127.0.0.1", 0))
    target.listen()
    target.settimeout(0.2)
    target_port = target.getsockname()[1]
    stop_target = threading.Event()

    def serve_target():
        while not stop_target.is_set():
            try:
                connection, _address = target.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with connection:
                connection.sendall(b"SSH-2.0-Xray-health-test\r\n")

    target_thread = threading.Thread(target=serve_target, daemon=True)
    target_thread.start()
    server = subprocess.Popen(
        [str(xray), "run", "-format", "json", "-config", "/dev/stdin"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    config = {
        "log": {"loglevel": "none"},
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": server_port,
                "protocol": "shadowsocks",
                "settings": {"method": "aes-128-gcm", "password": "health-secret"},
            }
        ],
        "outbounds": [{"protocol": "freedom", "settings": {}}],
    }
    server.stdin.write(json.dumps(config).encode())
    server.stdin.close()
    source = _SSH_PROBE.replace(
        'xray = "/usr/local/bin/xray"', f"xray = {json.dumps(str(xray))}"
    )
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if server.poll() is not None:
                pytest.fail("fixed Xray test server exited before accepting connections")
            try:
                with socket.create_connection(("127.0.0.1", server_port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            pytest.fail("fixed Xray test server did not start")

        result = subprocess.run(
            [sys.executable, "-c", source],
            input=json.dumps(
                {
                    "server_port": server_port,
                    "target_port": target_port,
                    "method": "aes-128-gcm",
                    "password": "health-secret",
                }
            ),
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
        assert result.returncode == 0
        assert json.loads(result.stdout) == {
            "accepted": True,
            "positive_control": True,
            "fresh_connection": True,
        }
    finally:
        server.terminate()
        try:
            server.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=3)
        stop_target.set()
        target.close()
        target_thread.join(timeout=1)


def test_pinned_bundle_download_checks_https_hash_and_size_before_returning():
    from apps.nodes.bootstrap_runtime import download_pinned_bundle

    body = b"pinned Linux Xray archive"
    digest = hashlib.sha256(body).hexdigest()

    class Response(io.BytesIO):
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

        def geturl(self):
            return "https://release-assets.githubusercontent.com/pinned.zip"

    opened = []

    def opener(request, *, timeout):
        opened.append((request.full_url, timeout))
        return Response(body)

    artifact = {
        "filename": "pinned.zip",
        "url": "https://github.com/XTLS/Xray-core/releases/download/tag/pinned.zip",
        "sha256": digest,
    }
    result = download_pinned_bundle(artifact, opener=opener, max_bytes=1024)

    assert result == body
    assert opened[0][1] > 0


@pytest.mark.parametrize(
    "artifact,expected_code",
    [
        (
            {"filename": "pinned.zip", "url": "http://github.com/pinned.zip", "sha256": "a" * 64},
            "BOOTSTRAP_ARTIFACT_URL_INVALID",
        ),
        (
            {"filename": "pinned.zip", "url": "https://github.com/pinned.zip", "sha256": "a" * 64},
            "BOOTSTRAP_ARTIFACT_HASH_MISMATCH",
        ),
    ],
)
def test_pinned_bundle_download_rejects_untrusted_or_unverified_artifact(
    artifact, expected_code
):
    from apps.nodes.bootstrap_runtime import download_pinned_bundle

    class Response(io.BytesIO):
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

        def geturl(self):
            return "https://github.com/pinned.zip"

    with pytest.raises(DomainError) as error:
        download_pinned_bundle(artifact, opener=lambda *_args, **_kwargs: Response(b"wrong"))

    assert error.value.code == expected_code


def test_pinned_bundle_download_rejects_response_larger_than_limit():
    from apps.nodes.bootstrap_runtime import download_pinned_bundle

    artifact = {
        "filename": "pinned.zip",
        "url": "https://github.com/pinned.zip",
        "sha256": hashlib.sha256(b"too large").hexdigest(),
    }

    class Response(io.BytesIO):
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

        def geturl(self):
            return "https://github.com/pinned.zip"

    with pytest.raises(DomainError) as error:
        download_pinned_bundle(
            artifact,
            opener=lambda *_args, **_kwargs: Response(b"too large"),
            max_bytes=2,
        )

    assert error.value.code == "BOOTSTRAP_ARTIFACT_TOO_LARGE"
