from __future__ import annotations

from typing import Literal

Format = Literal["shadowrocket", "clash", "mihomo", "v2ray"]

FORMAT_PROTOCOLS: dict[Format, frozenset[str]] = {
    "shadowrocket": frozenset({"shadowsocks", "socks5", "vmess", "vless", "trojan"}),
    "clash": frozenset({"shadowsocks", "socks5", "vmess", "trojan"}),
    "mihomo": frozenset({"shadowsocks", "socks5", "vmess", "vless", "trojan"}),
    "v2ray": frozenset({"shadowsocks", "socks5", "vmess", "vless", "trojan"}),
}

PARSER_VERSIONS = {
    "xray": "26.3.27",
    "clash": "1.18.0",
    "mihomo": "1.19.12",
}
