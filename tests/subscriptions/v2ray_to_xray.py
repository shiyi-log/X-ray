from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit


def decode(value: str, *, urlsafe: bool = False) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    decoder = base64.urlsafe_b64decode if urlsafe else base64.b64decode
    return decoder(padded)


def stream_settings(query: dict[str, list[str]]) -> dict | None:
    if query.get("security") != ["tls"]:
        return None
    settings = {"security": "tls"}
    server_name = query.get("sni", [""])[0]
    if server_name:
        settings["tlsSettings"] = {"serverName": server_name, "allowInsecure": False}
    return settings


def outbound(line: str) -> dict:
    if line.startswith("vmess://"):
        value = json.loads(decode(line.removeprefix("vmess://")))
        result = {
            "protocol": "vmess",
            "settings": {
                "vnext": [
                    {
                        "address": value["add"],
                        "port": int(value["port"]),
                        "users": [{"id": value["id"], "security": value["scy"]}],
                    }
                ]
            },
        }
        if value.get("tls") == "tls":
            result["streamSettings"] = {
                "security": "tls",
                "tlsSettings": {
                    "serverName": value.get("sni") or value["add"],
                    "allowInsecure": False,
                },
            }
        return result

    parsed = urlsplit(line)
    query = parse_qs(parsed.query)
    if parsed.scheme == "ss":
        method, password = decode(parsed.username or "", urlsafe=True).decode().split(":", 1)
        return {
            "protocol": "shadowsocks",
            "settings": {
                "servers": [
                    {
                        "address": parsed.hostname,
                        "port": parsed.port,
                        "method": method,
                        "password": password,
                    }
                ]
            },
        }
    if parsed.scheme == "socks":
        return {
            "protocol": "socks",
            "settings": {
                "servers": [
                    {
                        "address": parsed.hostname,
                        "port": parsed.port,
                        "users": [
                            {
                                "user": unquote(parsed.username or ""),
                                "pass": unquote(parsed.password or ""),
                            }
                        ],
                    }
                ]
            },
        }
    if parsed.scheme == "vless":
        result = {
            "protocol": "vless",
            "settings": {
                "vnext": [
                    {
                        "address": parsed.hostname,
                        "port": parsed.port,
                        "users": [
                            {
                                "id": parsed.username,
                                "encryption": query.get("encryption", ["none"])[0],
                            }
                        ],
                    }
                ]
            },
        }
    elif parsed.scheme == "trojan":
        result = {
            "protocol": "trojan",
            "settings": {
                "servers": [
                    {
                        "address": parsed.hostname,
                        "port": parsed.port,
                        "password": unquote(parsed.username or ""),
                    }
                ]
            },
        }
    else:
        raise ValueError(f"unsupported URI scheme: {parsed.scheme}")
    tls = stream_settings(query)
    if tls:
        result["streamSettings"] = tls
    return result


def main(source: str, destination: str) -> int:
    encoded = Path(source).read_text(encoding="ascii").strip()
    lines = decode(encoded).decode("utf-8").splitlines()
    document = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": 10808,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True},
            }
        ],
        "outbounds": [outbound(line) for line in lines],
    }
    Path(destination).write_text(
        json.dumps(document, separators=(",", ":")), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1], sys.argv[2]))
    except (IndexError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"V2Ray fixture conversion failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
