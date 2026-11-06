import base64
import hashlib
import struct
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from apps.subscriptions.node_agent import aws_transport


def test_aws_transport_limits_first_connection_to_provider_attested_host_keys(monkeypatch):
    now = datetime(2026, 11, 6, 4, 0, tzinfo=UTC)
    ed25519_blob = (
        struct.pack("!I", len(b"ssh-ed25519"))
        + b"ssh-ed25519"
        + struct.pack("!I", 32)
        + bytes(range(32))
    )
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(ed25519_blob).digest()
    ).decode().rstrip("=")
    access_details = {
        "certKey": None,
        "expiresAt": now + timedelta(hours=1),
        "ipAddress": "198.51.100.20",
        "ipv6Addresses": [],
        "password": "",
        "passwordData": "",
        "privateKey": "",
        "protocol": "ssh",
        "instanceName": "node-automation-test",
        "username": "ubuntu",
        "hostKeys": [
            {
                "algorithm": "ssh-ed25519",
                "publicKey": base64.b64encode(ed25519_blob).decode(),
                "witnessedAt": now,
                "fingerprintSHA1": "SHA1:fixture",
                "fingerprintSHA256": fingerprint,
            },
            {
                "algorithm": "ssh-ed25519",
                "publicKey": base64.b64encode(ed25519_blob).decode(),
                "witnessedAt": now + timedelta(minutes=1),
                "fingerprintSHA1": "SHA1:future",
                "fingerprintSHA256": "SHA256:" + "B" * 43,
            },
            {
                "algorithm": "ssh-ed25519",
                "publicKey": base64.b64encode(ed25519_blob).decode(),
                "witnessedAt": now,
                "fingerprintSHA1": "SHA1:malformed",
                "fingerprintSHA256": "SHA256:short",
            },
        ],
    }
    provider = SimpleNamespace(
        lightsail=SimpleNamespace(
            get_instance_access_details=lambda **_kwargs: {
                "accessDetails": access_details
            }
        )
    )
    monkeypatch.setattr(
        "apps.subscriptions.node_agent.build_read_provider",
        lambda *_args: SimpleNamespace(_provider=provider),
    )
    captured = {}

    def transport_factory(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(
        "apps.subscriptions.node_agent.ParamikoApplyTransport", transport_factory
    )
    node = SimpleNamespace(
        pk=uuid4(),
        region="ap-southeast-1",
        external_id="node-automation-test",
        cloud_account_id=uuid4(),
        cloud_account=SimpleNamespace(provider="aws_lightsail"),
    )

    aws_transport(node)

    assert captured["host"] == "198.51.100.20"
    assert captured["attested_fingerprints"] == (fingerprint,)


def test_usage_collection_defaults_to_the_builtin_lightsail_agent(settings, monkeypatch):
    from apps.subscriptions.metering import collect_node

    settings.XRAY_USAGE_FETCHER = "apps.subscriptions.node_agent.fetch_usage"
    node = SimpleNamespace(
        applied_generation=7,
        cloud_account=SimpleNamespace(provider="aws_lightsail"),
    )
    resolved = []
    called = []

    def fetcher(candidate):
        called.append(candidate)
        return {"stat": []}

    monkeypatch.setattr(
        "apps.subscriptions.metering.import_string",
        lambda path: resolved.append(path) or fetcher,
    )
    monkeypatch.setattr(
        "apps.subscriptions.metering.ingest_snapshot",
        lambda candidate, snapshot: (candidate, snapshot),
    )
    assert collect_node(node) == (node, {"stat": []})

    assert resolved == ["apps.subscriptions.node_agent.fetch_usage"]
    assert called == [node]
