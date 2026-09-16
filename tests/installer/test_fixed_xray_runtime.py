from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


def free_port():
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_port(port, process, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(f"Xray exited early: {stdout} {stderr}")
        with closing(socket.socket()) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise AssertionError(f"Xray did not listen on {port}")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"xray-runtime-ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


def process_env():
    return {
        key: value
        for key, value in os.environ.items()
        if key.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    }


def xray_binary():
    value = os.getenv("XRAY_TEST_BINARY")
    required = os.getenv("XRAY_REQUIRE_FIXED_BINARY") == "1"
    if not value or not Path(value).is_file():
        if required:
            pytest.fail("XRAY_TEST_BINARY is required by the fixed-runtime gate")
        pytest.skip("fixed Xray test binary is not configured")
    completed = subprocess.run(
        [value, "version"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0
    assert "26.3.27" in completed.stdout.splitlines()[0]
    return value


def write_config(path, value):
    path.write_text(json.dumps(value, separators=(",", ":")))
    return path


def run_xray(binary, config):
    return subprocess.Popen(
        [binary, "run", "-config", str(config)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=process_env(),
    )


def test_fixed_xray_serves_five_protocols(tmp_path):
    binary = xray_binary()
    server_ports = {name: free_port() for name in ("ss", "socks", "vmess", "vless", "trojan")}
    target_port = free_port()
    identity = "11111111-1111-4111-8111-111111111111"
    server = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "ss",
                "listen": "127.0.0.1",
                "port": server_ports["ss"],
                "protocol": "shadowsocks",
                "settings": {
                    "method": "aes-128-gcm",
                    "password": "local-test-password",
                    "network": "tcp,udp",
                },
            },
            {
                "tag": "socks",
                "listen": "127.0.0.1",
                "port": server_ports["socks"],
                "protocol": "socks",
                "settings": {
                    "auth": "password",
                    "accounts": [{"user": "local", "pass": "local-test-password"}],
                    "udp": True,
                },
            },
            {
                "tag": "vmess",
                "listen": "127.0.0.1",
                "port": server_ports["vmess"],
                "protocol": "vmess",
                "settings": {"clients": [{"id": identity}]},
            },
            {
                "tag": "vless",
                "listen": "127.0.0.1",
                "port": server_ports["vless"],
                "protocol": "vless",
                "settings": {"clients": [{"id": identity}], "decryption": "none"},
            },
            {
                "tag": "trojan",
                "listen": "127.0.0.1",
                "port": server_ports["trojan"],
                "protocol": "trojan",
                "settings": {"clients": [{"password": "local-test-password"}]},
            },
        ],
        "outbounds": [{"protocol": "freedom", "tag": "direct"}],
    }
    server_config = write_config(tmp_path / "server.json", server)
    checked = subprocess.run(
        [binary, "run", "-test", "-config", str(server_config)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr

    httpd = ThreadingHTTPServer(("127.0.0.1", target_port), Handler)
    http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    http_thread.start()
    server_process = run_xray(binary, server_config)
    clients = []
    try:
        wait_port(server_ports["socks"], server_process)
        cases = {
            "ss": {
                "protocol": "shadowsocks",
                "settings": {
                    "servers": [
                        {
                            "address": "127.0.0.1",
                            "port": server_ports["ss"],
                            "method": "aes-128-gcm",
                            "password": "local-test-password",
                        }
                    ]
                },
            },
            "vmess": {
                "protocol": "vmess",
                "settings": {
                    "vnext": [
                        {
                            "address": "127.0.0.1",
                            "port": server_ports["vmess"],
                            "users": [{"id": identity, "security": "auto"}],
                        }
                    ]
                },
            },
            "vless": {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": "127.0.0.1",
                            "port": server_ports["vless"],
                            "users": [{"id": identity, "encryption": "none"}],
                        }
                    ]
                },
            },
            "trojan": {
                "protocol": "trojan",
                "settings": {
                    "servers": [
                        {
                            "address": "127.0.0.1",
                            "port": server_ports["trojan"],
                            "password": "local-test-password",
                        }
                    ]
                },
            },
        }
        proxy_ports = {"socks": server_ports["socks"]}
        for name, outbound in cases.items():
            proxy_port = free_port()
            proxy_ports[name] = proxy_port
            config = {
                "log": {"loglevel": "warning"},
                "inbounds": [
                    {
                        "listen": "127.0.0.1",
                        "port": proxy_port,
                        "protocol": "socks",
                        "settings": {"auth": "noauth", "udp": True},
                    }
                ],
                "outbounds": [outbound],
            }
            client = run_xray(binary, write_config(tmp_path / f"{name}.json", config))
            clients.append(client)
            wait_port(proxy_port, client)

        for name, proxy_port in proxy_ports.items():
            command = [
                "curl",
                "--disable",
                "--silent",
                "--show-error",
                "--fail",
                "--max-time",
                "5",
                "--socks5-hostname",
                f"127.0.0.1:{proxy_port}",
            ]
            if name == "socks":
                command.extend(["--proxy-user", "local:local-test-password"])
            command.append(f"http://127.0.0.1:{target_port}/")
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                env=process_env(),
                check=False,
            )
            assert completed.returncode == 0, f"{name}: {completed.stderr}"
            assert completed.stdout == "xray-runtime-ok"
    finally:
        for process in clients:
            process.terminate()
            process.wait(timeout=5)
        server_process.terminate()
        server_process.wait(timeout=5)
        httpd.shutdown()
        httpd.server_close()
