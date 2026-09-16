from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


def decode_base64(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4), validate=True)


def main(path: str) -> int:
    encoded = Path(path).read_text(encoding="ascii").strip()
    lines = decode_base64(encoded).decode("utf-8").splitlines()
    schemes = [urlsplit(line).scheme for line in lines]
    if schemes != ["ss", "socks", "vmess", "vless", "trojan"]:
        raise ValueError("unexpected Shadowrocket fixture protocol order")

    ss = urlsplit(lines[0])
    method, password = decode_base64(ss.username or "").decode("utf-8").split(":", 1)
    if (method, password, ss.hostname, ss.port) != (
        "aes-128-gcm",
        "test-only-password",
        "127.0.0.1",
        10001,
    ):
        raise ValueError("invalid Shadowsocks URI")

    socks = urlsplit(lines[1])
    if (socks.username, socks.password, socks.hostname, socks.port) != (
        "fixture",
        "fixture-pass",
        "127.0.0.1",
        10002,
    ):
        raise ValueError("invalid SOCKS URI")

    vmess = json.loads(decode_base64(lines[2].removeprefix("vmess://")))
    if vmess.get("id") != "11111111-1111-4111-8111-111111111111":
        raise ValueError("invalid VMess URI")

    vless = urlsplit(lines[3])
    if parse_qs(vless.query).get("encryption") != ["none"]:
        raise ValueError("invalid VLESS URI")
    if urlsplit(lines[4]).username != "test-only-password":
        raise ValueError("invalid Trojan URI")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1]))
    except (IndexError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"fixture verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
