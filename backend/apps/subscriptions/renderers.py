from __future__ import annotations

import base64
import ipaddress
import json
from urllib.parse import quote, urlencode

import yaml

from common.errors import DomainError

from .compatibility import FORMAT_PROTOCOLS, Format


class NoCompatibleEndpoints(DomainError):
    def __init__(self):
        super().__init__(
            "NO_COMPATIBLE_ENDPOINTS", "该订阅格式没有兼容节点", status_code=422
        )


def _host(value: str) -> str:
    try:
        return f"[{value}]" if ipaddress.ip_address(value).version == 6 else value
    except ValueError:
        return value


def _tls_query(endpoint: dict) -> dict:
    if endpoint.get("allow_insecure"):
        raise DomainError(
            "INSECURE_TLS_FORBIDDEN", "生产订阅禁止跳过 TLS 验证", status_code=422
        )
    if not endpoint.get("tls"):
        return {}
    values = {"security": "tls"}
    if endpoint.get("server_name"):
        values["sni"] = endpoint["server_name"]
    return values


def _uri(endpoint: dict) -> str:
    protocol = endpoint["protocol"]
    host = _host(str(endpoint["host"]))
    port = int(endpoint["port"])
    name = quote(str(endpoint.get("name") or protocol), safe="")
    credential = endpoint["credential"]
    query = {"type": endpoint.get("transport") or "tcp", **_tls_query(endpoint)}
    if protocol == "shadowsocks":
        userinfo = base64.urlsafe_b64encode(
            f"{credential['method']}:{credential['password']}".encode()
        ).decode().rstrip("=")
        return f"ss://{userinfo}@{host}:{port}#{name}"
    if protocol == "socks5":
        username = quote(credential["username"], safe="")
        password = quote(credential["password"], safe="")
        return f"socks://{username}:{password}@{host}:{port}#{name}"
    if protocol == "vmess":
        payload = {
            "v": "2",
            "ps": endpoint.get("name") or "vmess",
            "add": endpoint["host"],
            "port": str(port),
            "id": credential["id"],
            "aid": "0",
            "scy": "auto",
            "net": endpoint.get("transport") or "tcp",
            "type": "none",
            "host": "",
            "path": "",
            "tls": "tls" if endpoint.get("tls") else "",
            "sni": endpoint.get("server_name") or "",
        }
        encoded = base64.b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        ).decode()
        return f"vmess://{encoded}"
    if protocol == "vless":
        query["encryption"] = "none"
        return f"vless://{credential['id']}@{host}:{port}?{urlencode(query)}#{name}"
    if protocol == "trojan":
        password = quote(credential["password"], safe="")
        return f"trojan://{password}@{host}:{port}?{urlencode(query)}#{name}"
    raise DomainError("PROTOCOL_UNSUPPORTED", "不支持的节点协议", status_code=422)


def _yaml_proxy(endpoint: dict, *, mihomo: bool) -> dict:
    protocol = endpoint["protocol"]
    credential = endpoint["credential"]
    proxy = {
        "name": endpoint.get("name") or protocol,
        "type": protocol,
        "server": endpoint["host"],
        "port": int(endpoint["port"]),
    }
    if protocol == "shadowsocks":
        proxy.update(
            {
                "type": "ss",
                "cipher": credential["method"],
                "password": credential["password"],
            }
        )
    elif protocol == "socks5":
        proxy.update(
            {
                "type": "socks5",
                "username": credential["username"],
                "password": credential["password"],
            }
        )
    elif protocol == "vmess":
        proxy.update({"uuid": credential["id"], "alterId": 0, "cipher": "auto"})
    elif protocol == "vless":
        proxy.update({"uuid": credential["id"], "network": endpoint.get("transport") or "tcp"})
        if mihomo:
            proxy["client-fingerprint"] = "chrome"
    elif protocol == "trojan":
        proxy["password"] = credential["password"]
    _tls_query(endpoint)
    if endpoint.get("tls"):
        proxy["tls"] = True
        proxy["servername"] = endpoint.get("server_name")
        proxy["skip-cert-verify"] = False
    return proxy


def render_subscription(
    format: Format,
    *,
    endpoints: list[dict],
    public_version: str,
) -> bytes:
    if format not in FORMAT_PROTOCOLS:
        raise DomainError("SUBSCRIPTION_FORMAT_UNKNOWN", "订阅格式不支持", status_code=422)
    compatible = [
        endpoint
        for endpoint in endpoints
        if endpoint.get("protocol") in FORMAT_PROTOCOLS[format]
    ]
    if not compatible:
        raise NoCompatibleEndpoints()
    if format in {"shadowrocket", "v2ray"}:
        body = "\n".join(_uri(endpoint) for endpoint in compatible) + "\n"
        return base64.b64encode(body.encode())
    proxies = [
        _yaml_proxy(endpoint, mihomo=format == "mihomo") for endpoint in compatible
    ]
    document = {
        "x-public-version": public_version,
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "X-ray",
                "type": "select",
                "proxies": [proxy["name"] for proxy in proxies],
            }
        ],
        "rules": ["MATCH,X-ray"],
    }
    return yaml.safe_dump(document, allow_unicode=True, sort_keys=False).encode()
