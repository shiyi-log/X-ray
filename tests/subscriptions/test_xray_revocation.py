from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import threading
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


def free_port() -> int:
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def process_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    }


def fixed_xray_binary() -> str:
    value = os.getenv("XRAY_TEST_BINARY")
    required = os.getenv("XRAY_REQUIRE_FIXED_BINARY") == "1"
    if not value or not Path(value).is_file():
        if required:
            pytest.fail("XRAY_TEST_BINARY is required by the fixed revocation gate")
        pytest.skip("fixed Xray test binary is not configured")
    completed = subprocess.run(
        [value, "version"],
        capture_output=True,
        text=True,
        check=False,
        env=process_env(),
    )
    assert completed.returncode == 0
    assert completed.stdout.splitlines()[0].startswith("Xray 26.3.27 ")
    return value


def write_config(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    return path


def run_xray(binary: str, config: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [binary, "run", "-config", str(config)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=process_env(),
    )


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def wait_port(port: int, process: subprocess.Popen, timeout: float = 8) -> None:
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


class TargetHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    release_holds = threading.Event()

    def do_GET(self):
        if self.path == "/hold":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"hold-open\n")
            self.wfile.flush()
            self.release_holds.wait(timeout=30)
            return
        body = b"revocation-positive-control"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


def server_config(ports: dict[str, int], credentials: dict[str, str]) -> dict:
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "ss",
                "listen": "127.0.0.1",
                "port": ports["ss"],
                "protocol": "shadowsocks",
                "settings": {
                    "method": "aes-128-gcm",
                    "password": credentials["ss"],
                    "network": "tcp",
                },
            },
            {
                "tag": "socks",
                "listen": "127.0.0.1",
                "port": ports["socks"],
                "protocol": "socks",
                "settings": {
                    "auth": "password",
                    "accounts": [
                        {
                            "user": credentials["socks_user"],
                            "pass": credentials["socks_password"],
                        }
                    ],
                    "udp": False,
                },
            },
            {
                "tag": "vmess",
                "listen": "127.0.0.1",
                "port": ports["vmess"],
                "protocol": "vmess",
                "settings": {"clients": [{"id": credentials["vmess"]}]},
            },
            {
                "tag": "vless",
                "listen": "127.0.0.1",
                "port": ports["vless"],
                "protocol": "vless",
                "settings": {
                    "clients": [{"id": credentials["vless"]}],
                    "decryption": "none",
                },
            },
            {
                "tag": "trojan",
                "listen": "127.0.0.1",
                "port": ports["trojan"],
                "protocol": "trojan",
                "settings": {
                    "clients": [{"password": credentials["trojan"]}]
                },
            },
        ],
        "outbounds": [{"protocol": "freedom", "tag": "direct"}],
    }


def client_outbound(protocol: str, port: int, credentials: dict[str, str]) -> dict:
    if protocol == "ss":
        return {
            "protocol": "shadowsocks",
            "settings": {
                "servers": [
                    {
                        "address": "127.0.0.1",
                        "port": port,
                        "method": "aes-128-gcm",
                        "password": credentials["ss"],
                    }
                ]
            },
        }
    if protocol == "socks":
        return {
            "protocol": "socks",
            "settings": {
                "servers": [
                    {
                        "address": "127.0.0.1",
                        "port": port,
                        "users": [
                            {
                                "user": credentials["socks_user"],
                                "pass": credentials["socks_password"],
                            }
                        ],
                    }
                ]
            },
        }
    if protocol == "vmess":
        return {
            "protocol": "vmess",
            "settings": {
                "vnext": [
                    {
                        "address": "127.0.0.1",
                        "port": port,
                        "users": [{"id": credentials["vmess"], "security": "auto"}],
                    }
                ]
            },
        }
    if protocol == "vless":
        return {
            "protocol": "vless",
            "settings": {
                "vnext": [
                    {
                        "address": "127.0.0.1",
                        "port": port,
                        "users": [
                            {"id": credentials["vless"], "encryption": "none"}
                        ],
                    }
                ]
            },
        }
    return {
        "protocol": "trojan",
        "settings": {
            "servers": [
                {
                    "address": "127.0.0.1",
                    "port": port,
                    "password": credentials["trojan"],
                }
            ]
        },
    }


def client_config(proxy_port: int, outbound: dict) -> dict:
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": proxy_port,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": False},
            }
        ],
        "outbounds": [outbound],
    }


def curl_through(proxy_port: int, target_port: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "curl",
            "--disable",
            "--silent",
            "--show-error",
            "--fail",
            "--max-time",
            "3",
            "--socks5-hostname",
            f"127.0.0.1:{proxy_port}",
            f"http://127.0.0.1:{target_port}/",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=process_env(),
    )


def recv_exact(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("SOCKS connection closed")
        data += chunk
    return data


def open_hold(proxy_port: int, target_port: int) -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", proxy_port), timeout=3)
    sock.sendall(b"\x05\x01\x00")
    if recv_exact(sock, 2) != b"\x05\x00":
        raise ConnectionError("SOCKS authentication negotiation failed")
    sock.sendall(
        b"\x05\x01\x00\x01"
        + socket.inet_aton("127.0.0.1")
        + struct.pack("!H", target_port)
    )
    header = recv_exact(sock, 4)
    if header[1] != 0:
        raise ConnectionError(f"SOCKS connect failed with code {header[1]}")
    address_size = {1: 4, 4: 16}.get(header[3])
    if header[3] == 3:
        address_size = recv_exact(sock, 1)[0]
    if address_size is None:
        raise ConnectionError("SOCKS returned an unknown address type")
    recv_exact(sock, address_size + 2)
    sock.sendall(
        b"GET /hold HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: keep-alive\r\n\r\n"
    )
    response = b""
    while b"hold-open\n" not in response:
        response += sock.recv(4096)
    return sock


def assert_connection_closed(sock: socket.socket, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    sock.settimeout(0.2)
    while time.monotonic() < deadline:
        try:
            if sock.recv(1) == b"":
                return
        except (ConnectionResetError, BrokenPipeError):
            return
        except socket.timeout:
            continue
    raise AssertionError("old authenticated session remained open after revocation")


def test_fixed_xray_rejects_old_five_protocol_credentials_and_closes_sessions(
    tmp_path,
):
    binary = fixed_xray_binary()
    protocols = ("ss", "socks", "vmess", "vless", "trojan")
    server_ports = {protocol: free_port() for protocol in protocols}
    target_port = free_port()
    old = {
        "ss": "shared-old-password",
        "socks_user": "old-user",
        "socks_password": "old-password",
        "vmess": "11111111-1111-4111-8111-111111111111",
        "vless": "22222222-2222-4222-8222-222222222222",
        "trojan": "old-trojan-password",
    }
    new = {
        "ss": "shared-new-password",
        "socks_user": "new-user",
        "socks_password": "new-password",
        "vmess": "33333333-3333-4333-8333-333333333333",
        "vless": "44444444-4444-4444-8444-444444444444",
        "trojan": "new-trojan-password",
    }
    old_labels = ("ss-profile-a", "ss-profile-b", "socks", "vmess", "vless", "trojan")
    old_protocol = {
        "ss-profile-a": "ss",
        "ss-profile-b": "ss",
        "socks": "socks",
        "vmess": "vmess",
        "vless": "vless",
        "trojan": "trojan",
    }
    TargetHandler.release_holds.clear()
    target = ThreadingHTTPServer(("127.0.0.1", target_port), TargetHandler)
    target_thread = threading.Thread(target=target.serve_forever, daemon=True)
    target_thread.start()
    processes: list[subprocess.Popen] = []
    held: list[socket.socket] = []
    server = None
    try:
        old_server_config = write_config(
            tmp_path / "server-old.json", server_config(server_ports, old)
        )
        checked = subprocess.run(
            [binary, "run", "-test", "-config", str(old_server_config)],
            capture_output=True,
            text=True,
            check=False,
            env=process_env(),
        )
        assert checked.returncode == 0, checked.stderr
        server = run_xray(binary, old_server_config)
        wait_port(server_ports["socks"], server)

        old_proxy_ports = {}
        for label in old_labels:
            protocol = old_protocol[label]
            proxy_port = free_port()
            old_proxy_ports[label] = proxy_port
            path = write_config(
                tmp_path / f"client-old-{label}.json",
                client_config(
                    proxy_port,
                    client_outbound(protocol, server_ports[protocol], old),
                ),
            )
            process = run_xray(binary, path)
            processes.append(process)
            wait_port(proxy_port, process)
            control = curl_through(proxy_port, target_port)
            assert control.returncode == 0, f"{label}: {control.stderr}"
            held.append(open_hold(proxy_port, target_port))

        stop_process(server)
        server = None
        new_server_config = write_config(
            tmp_path / "server-new.json", server_config(server_ports, new)
        )
        server = run_xray(binary, new_server_config)
        wait_port(server_ports["socks"], server)

        for sock in held:
            assert_connection_closed(sock)
        for label, proxy_port in old_proxy_ports.items():
            rejected = curl_through(proxy_port, target_port)
            assert rejected.returncode != 0, f"old {label} credential still connected"

        for protocol in protocols:
            proxy_port = free_port()
            path = write_config(
                tmp_path / f"client-new-{protocol}.json",
                client_config(
                    proxy_port,
                    client_outbound(protocol, server_ports[protocol], new),
                ),
            )
            process = run_xray(binary, path)
            processes.append(process)
            wait_port(proxy_port, process)
            accepted = curl_through(proxy_port, target_port)
            assert accepted.returncode == 0, f"new {protocol}: {accepted.stderr}"
            assert accepted.stdout == "revocation-positive-control"
    finally:
        TargetHandler.release_holds.set()
        for sock in held:
            sock.close()
        for process in processes:
            stop_process(process)
        if server is not None:
            stop_process(server)
        target.shutdown()
        target.server_close()
