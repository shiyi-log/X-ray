from __future__ import annotations

from dataclasses import dataclass

from common.errors import DomainError


@dataclass(frozen=True, slots=True)
class ProtocolCapability:
    tcp: bool
    udp: bool
    credential_modes: tuple[str, ...]
    individual_revocation_modes: tuple[str, ...]
    transports: tuple[str, ...]


PROTOCOL_CAPABILITIES = {
    "shadowsocks": ProtocolCapability(True, True, ("shared", "profile"), ("profile",), ("tcp",)),
    "socks5": ProtocolCapability(True, True, ("profile",), ("profile",), ("tcp",)),
    "vmess": ProtocolCapability(True, True, ("profile",), ("profile",), ("tcp", "ws", "grpc")),
    "vless": ProtocolCapability(True, True, ("profile",), ("profile",), ("tcp", "ws", "grpc")),
    "trojan": ProtocolCapability(
        True, True, ("profile", "shared"), ("profile",), ("tcp", "ws", "grpc")
    ),
}


def validate_protocol_config(protocol: str, config: dict) -> dict:
    try:
        capability = PROTOCOL_CAPABILITIES[protocol]
    except KeyError as exc:
        raise DomainError("PROTOCOL_UNSUPPORTED", "不支持的节点协议", status_code=400) from exc
    scope = str(config.get("credential_scope") or "profile")
    transport = str(config.get("transport") or "tcp")
    if scope not in capability.credential_modes:
        raise DomainError("CREDENTIAL_SCOPE_UNSUPPORTED", "凭据作用域不受支持", status_code=400)
    if transport not in capability.transports:
        raise DomainError("TRANSPORT_UNSUPPORTED", "传输方式不受支持", status_code=400)
    individual = scope in capability.individual_revocation_modes
    return {
        "supported": True,
        "tcp": capability.tcp,
        "udp": capability.udp,
        "individual_revocation": individual,
        "shared_credential_impact": not individual,
    }
