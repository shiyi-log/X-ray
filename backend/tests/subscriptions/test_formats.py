import base64
import json
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml
from common.errors import DomainError


def endpoint(protocol, **overrides):
    base = {
        "node_id": "11111111-1111-4111-8111-111111111111",
        "name": f"node-{protocol}",
        "protocol": protocol,
        "host": "2001:db8::1",
        "port": 443,
        "transport": "tcp",
        "tls": True,
        "server_name": "proxy.example.test",
        "credential_ref": "22222222-2222-4222-8222-222222222222",
        "credential_version": 1,
        "applied_generation": 1,
        "credential": {
            "id": "33333333-3333-4333-8333-333333333333",
            "username": "user@example.test",
            "password": "p@ss word",
            "method": "aes-128-gcm",
        },
    }
    base.update(overrides)
    return base


def decode_lines(payload):
    return base64.b64decode(payload).decode().strip().splitlines()


def test_empty_protocol_intersection_is_an_explicit_error():
    from apps.subscriptions.renderers import NoCompatibleEndpoints, render_subscription

    with pytest.raises(NoCompatibleEndpoints):
        render_subscription("clash", endpoints=[], public_version="r-1")


def test_clash_and_mihomo_use_distinct_protocol_sets():
    from apps.subscriptions.renderers import render_subscription

    endpoints = [endpoint("vless"), endpoint("trojan")]
    clash = yaml.safe_load(render_subscription("clash", endpoints=endpoints, public_version="r1"))
    mihomo = yaml.safe_load(render_subscription("mihomo", endpoints=endpoints, public_version="r1"))
    assert [proxy["type"] for proxy in clash["proxies"]] == ["trojan"]
    assert {proxy["type"] for proxy in mihomo["proxies"]} == {"vless", "trojan"}
    assert "client-fingerprint" not in clash["proxies"][0]


def test_unified_mihomo_subscription_contains_every_supported_protocol():
    from apps.nodes.protocols import PROTOCOL_CAPABILITIES
    from apps.subscriptions.renderers import render_subscription

    document = yaml.safe_load(
        render_subscription(
            "mihomo",
            endpoints=[endpoint(name) for name in PROTOCOL_CAPABILITIES],
            public_version="unified",
        )
    )

    expected_types = {"ss" if name == "shadowsocks" else name for name in PROTOCOL_CAPABILITIES}
    assert {proxy["type"] for proxy in document["proxies"]} == expected_types


def test_v2ray_uris_escape_userinfo_bracket_ipv6_and_include_tls_sni():
    from apps.subscriptions.renderers import render_subscription

    lines = decode_lines(
        render_subscription(
            "v2ray",
            endpoints=[endpoint("socks5"), endpoint("vless")],
            public_version="r2",
        )
    )
    socks = urlsplit(lines[0])
    assert socks.scheme == "socks"
    assert socks.hostname == "2001:db8::1"
    assert "%40" in lines[0] and "%20" in lines[0]
    vless = urlsplit(lines[1])
    assert vless.hostname == "2001:db8::1"
    assert parse_qs(vless.query)["security"] == ["tls"]
    assert parse_qs(vless.query)["sni"] == ["proxy.example.test"]


def test_shadowrocket_vmess_contains_valid_base64_json_and_newline():
    from apps.subscriptions.renderers import render_subscription

    payload = render_subscription(
        "shadowrocket", endpoints=[endpoint("vmess")], public_version="r3"
    )
    lines = decode_lines(payload)
    assert len(lines) == 1
    assert lines[0].startswith("vmess://")
    vmess = json.loads(base64.b64decode(lines[0].removeprefix("vmess://")))
    assert vmess["add"] == "2001:db8::1"
    assert vmess["sni"] == "proxy.example.test"


def test_allow_insecure_is_rejected_for_all_formats():
    from apps.subscriptions.renderers import render_subscription

    insecure = endpoint("trojan", allow_insecure=True)
    with pytest.raises(DomainError) as caught:
        render_subscription("mihomo", endpoints=[insecure], public_version="r4")
    assert caught.value.code == "INSECURE_TLS_FORBIDDEN"


@pytest.mark.parametrize("format", ["clash", "mihomo"])
def test_yaml_subscriptions_enable_udp_for_every_compatible_protocol(format):
    from apps.nodes.protocols import PROTOCOL_CAPABILITIES
    from apps.subscriptions.compatibility import FORMAT_PROTOCOLS
    from apps.subscriptions.renderers import render_subscription

    document = yaml.safe_load(
        render_subscription(
            format,
            endpoints=[endpoint(name) for name in PROTOCOL_CAPABILITIES],
            public_version="udp-all",
        )
    )
    proxies = document["proxies"]
    assert len(proxies) == len(FORMAT_PROTOCOLS[format])
    assert all(proxy["udp"] is True for proxy in proxies)
