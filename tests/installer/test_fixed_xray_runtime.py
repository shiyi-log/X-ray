from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

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
    completed = subprocess.run([value, "version"], capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    assert "26.3.27" in completed.stdout.splitlines()[0]
    return value


def write_config(path, value):
    path.write_text(json.dumps(value, separators=(",", ":")))
    path.chmod(0o600)
    return path


def run_xray(binary, config):
    return subprocess.Popen(
        [binary, "run", "-config", str(config)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=process_env(),
    )


def check_udp_proxy(proxy_port, target_port, *, authenticated):
    # Keep the SOCKS TCP control channel alive throughout UDP association.
    with socket.create_connection(("127.0.0.1", proxy_port), timeout=5) as control:
        control.settimeout(5)

        def receive(size):
            data = b""
            while len(data) < size:
                chunk = control.recv(size - len(data))
                assert chunk, "SOCKS control channel closed"
                data += chunk
            return data

        method = 2 if authenticated else 0
        control.sendall(bytes([5, 1, method]))
        assert receive(2) == bytes([5, method])
        if authenticated:
            username, password = b"local", b"local-test-password"
            control.sendall(
                bytes([1, len(username)]) + username + bytes([len(password)]) + password
            )
            assert receive(2) == b"\x01\x00"
        control.sendall(b"\x05\x03\x00\x01" + b"\x00" * 6)
        header = receive(4)
        assert header[:3] == b"\x05\x00\x00"
        assert header[3] == 1
        host = socket.inet_ntoa(receive(4))
        port = int.from_bytes(receive(2), "big")
        payload = b"xray-udp-runtime-ok"
        packet = (
            b"\x00\x00\x00\x01"
            + socket.inet_aton("127.0.0.1")
            + target_port.to_bytes(2, "big")
            + payload
        )
        with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as udp:
            udp.settimeout(5)
            udp.sendto(packet, (host, port))
            response, _ = udp.recvfrom(4096)
            assert response[:4] == b"\x00\x00\x00\x01"
            assert response[10:] == payload


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
    udp_target = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_target.bind(("127.0.0.1", 0))
    udp_target.settimeout(0.2)
    udp_stop = threading.Event()

    def echo_udp():
        while not udp_stop.is_set():
            try:
                payload, address = udp_target.recvfrom(4096)
                udp_target.sendto(payload, address)
            except TimeoutError:
                continue

    udp_thread = threading.Thread(target=echo_udp, daemon=True)
    udp_thread.start()
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
        # The clients consume the actual manager's Mihomo export.
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
        import yaml
        from apps.subscriptions.renderers import render_subscription

        endpoints = [
            {
                "protocol": protocol,
                "name": name,
                "host": "127.0.0.1",
                "port": server_ports[name],
                "transport": "tcp",
                "tls": False,
                "credential": {
                    "id": identity,
                    "username": "local",
                    "password": "local-test-password",
                    "method": "aes-128-gcm",
                },
            }
            for name, protocol in [
                ("ss", "shadowsocks"),
                ("socks", "socks5"),
                ("vmess", "vmess"),
                ("vless", "vless"),
                ("trojan", "trojan"),
            ]
        ]
        exported = yaml.safe_load(
            render_subscription("mihomo", endpoints=endpoints, public_version="runtime-test")
        )
        assert len(exported["proxies"]) == 5
        for proxy in exported["proxies"]:
            name = proxy["name"]
            if name == "socks":
                assert proxy["username"] == "local" and proxy["password"] == "local-test-password"
            elif name in {"vmess", "vless"}:
                cases[name]["settings"]["vnext"][0] = {
                    "address": proxy["server"],
                    "port": proxy["port"],
                    "users": [
                        {
                            "id": proxy["uuid"],
                            **({"encryption": "none"} if name == "vless" else {"security": "auto"}),
                        }
                    ],
                }
            else:
                server = {
                    "address": proxy["server"],
                    "port": proxy["port"],
                    "password": proxy["password"],
                }
                if name == "ss":
                    server["method"] = proxy["cipher"]
                cases[name]["settings"]["servers"] = [server]
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
            check_udp_proxy(proxy_port, udp_target.getsockname()[1], authenticated=name == "socks")
            if os.getenv("XRAY_RUN_PUBLIC_PROBES") == "1":
                for target, expected in [
                    ("https://www.google.com/generate_204", 204),
                    ("https://www.youtube.com/", 200),
                ]:
                    probe = [
                        "curl",
                        "--disable",
                        "--silent",
                        "--show-error",
                        "--location",
                        "--proto",
                        "=https",
                        "--proto-redir",
                        "=https",
                        "--max-redirs",
                        "3",
                        "--connect-timeout",
                        "8",
                        "--max-time",
                        "20",
                        "--max-filesize",
                        "2097152",
                        "--socks5-hostname",
                        f"127.0.0.1:{proxy_port}",
                        "--output",
                        "/dev/null",
                        "--write-out",
                        "%{http_code} %{ssl_verify_result} %{url_effective}",
                    ]
                    if name == "socks":
                        probe.extend(["--proxy-user", "local:local-test-password"])
                    response = subprocess.run(
                        probe + [target],
                        capture_output=True,
                        text=True,
                        env=process_env(),
                        check=False,
                        timeout=25,
                    )
                    fields = response.stdout.split()
                    status = int(fields[0]) if fields and fields[0].isdecimal() else 0
                    verified = len(fields) >= 3 and fields[1] == "0"
                    host = urlsplit(fields[2]).hostname if len(fields) >= 3 else None
                    domain = "google.com" if expected == 204 else "youtube.com"
                    matched = bool(host and (host == domain or host.endswith("." + domain)))
                    entry = {
                        "protocol": name,
                        "target": urlsplit(target).hostname,
                        "curl_exit": response.returncode,
                        "http_status": status,
                        "tls_verified": verified,
                        "target_host_matches": matched,
                    }
                    print(json.dumps(entry))
                    report = os.getenv("XRAY_PUBLIC_PROBE_REPORT")
                    if report:
                        with open(report, "a") as stream:
                            stream.write(json.dumps(entry) + "\n")
                    assert (
                        response.returncode == 0 and status == expected and verified and matched
                    ), entry

    finally:
        udp_stop.set()
        udp_thread.join(timeout=1)
        udp_target.close()
        for process in clients:
            process.terminate()
            process.wait(timeout=5)
        server_process.terminate()
        server_process.wait(timeout=5)
        httpd.shutdown()
        httpd.server_close()
