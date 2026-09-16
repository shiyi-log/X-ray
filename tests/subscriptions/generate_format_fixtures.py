from __future__ import annotations

import sys
from pathlib import Path

from apps.subscriptions.renderers import render_subscription


def endpoints() -> list[dict]:
    common = {
        "node_id": "11111111-1111-4111-8111-111111111111",
        "host": "127.0.0.1",
        "transport": "tcp",
        "tls": False,
        "server_name": "",
        "credential_ref": "22222222-2222-4222-8222-222222222222",
        "credential_version": 1,
        "applied_generation": 1,
    }
    return [
        {
            **common,
            "name": "fixture-ss",
            "protocol": "shadowsocks",
            "port": 10001,
            "credential": {
                "method": "aes-128-gcm",
                "password": "test-only-password",
            },
        },
        {
            **common,
            "name": "fixture-socks",
            "protocol": "socks5",
            "port": 10002,
            "credential": {"username": "fixture", "password": "fixture-pass"},
        },
        {
            **common,
            "name": "fixture-vmess",
            "protocol": "vmess",
            "port": 10003,
            "credential": {"id": "11111111-1111-4111-8111-111111111111"},
        },
        {
            **common,
            "name": "fixture-vless",
            "protocol": "vless",
            "port": 10004,
            "credential": {"id": "22222222-2222-4222-8222-222222222222"},
        },
        {
            **common,
            "name": "fixture-trojan",
            "protocol": "trojan",
            "port": 10005,
            "credential": {"password": "test-only-password"},
        },
    ]


def main(output_dir: str) -> int:
    destination = Path(output_dir)
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    values = endpoints()
    for format, filename in (
        ("shadowrocket", "shadowrocket.txt"),
        ("clash", "clash.yaml"),
        ("mihomo", "mihomo.yaml"),
        ("v2ray", "v2ray.txt"),
    ):
        (destination / filename).write_bytes(
            render_subscription(format, endpoints=values, public_version="fixture-r1")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
