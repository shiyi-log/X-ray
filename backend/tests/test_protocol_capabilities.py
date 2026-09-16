from apps.nodes.protocols import PROTOCOL_CAPABILITIES, validate_protocol_config


def test_capability_matrix_covers_five_protocols():
    assert set(PROTOCOL_CAPABILITIES) == {
        "shadowsocks",
        "socks5",
        "vmess",
        "vless",
        "trojan",
    }
    for capability in PROTOCOL_CAPABILITIES.values():
        assert capability.tcp is True
        assert capability.credential_modes


def test_protocol_validation_reports_shared_credential_revocation_impact():
    result = validate_protocol_config(
        "shadowsocks",
        {"method": "2022-blake3-aes-128-gcm", "credential_scope": "shared"},
    )
    assert result["supported"] is True
    assert result["individual_revocation"] is False
    assert result["shared_credential_impact"] is True


def test_individual_vless_identity_supports_targeted_revocation():
    result = validate_protocol_config(
        "vless", {"transport": "tcp", "credential_scope": "profile"}
    )
    assert result["supported"] is True
    assert result["individual_revocation"] is True
