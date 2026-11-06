import io
import json
from types import SimpleNamespace
from uuid import uuid4


def test_fetch_usage_executes_pinned_stats_program_and_returns_json_contract(monkeypatch):
    from apps.subscriptions import node_agent

    profile_id = uuid4()
    payload = {
        "generation": 42,
        "boot_id": "boot-123",
        "process_id": "9876",
        "sequence": 19,
        "sampled_at": "2026-11-06T04:00:00+00:00",
        "stat": [
            {
                "name": f"user>>>profile-{profile_id}>>>traffic>>>uplink",
                "value": "120",
            },
            {
                "name": f"user>>>profile-{profile_id}>>>traffic>>>downlink",
                "value": 340,
            },
        ],
    }
    channel_state = {}

    class FakeChannel:
        def settimeout(self, timeout):
            channel_state["timeout"] = timeout

        def exec_command(self, command):
            channel_state["command"] = command

        def sendall(self, value):
            channel_state["script"] = value.decode()

        def shutdown_write(self):
            channel_state["shutdown_write"] = True

        def makefile(self, mode):
            assert mode == "rb"
            return io.BytesIO(json.dumps(payload).encode())

        def makefile_stderr(self, mode):
            assert mode == "rb"
            return io.BytesIO(b"")

        def recv_exit_status(self):
            return 0

    class FakeConnection:
        def __init__(self, _socket):
            channel_state["socket"] = _socket

        def start_client(self, timeout):
            channel_state["start_timeout"] = timeout

        def get_remote_server_key(self):
            return SimpleNamespace(asbytes=lambda: b"test-host-key")

        def auth_publickey(self, username, key):
            channel_state["auth"] = (username, key)

        def open_session(self, timeout):
            channel_state["session_timeout"] = timeout
            return FakeChannel()

        def close(self):
            channel_state["closed"] = True

    transport_info = SimpleNamespace(
        host="198.51.100.20",
        username="ubuntu",
        attested_fingerprints=("SHA256:attested",),
        host_key_attestation_source="test-provider",
        _authentication_key=lambda _paramiko: "private-key-object",
    )
    monkeypatch.setattr(node_agent, "aws_transport", lambda _node: transport_info)
    monkeypatch.setattr(
        node_agent.socket,
        "create_connection",
        lambda address, timeout: (address, timeout),
    )
    monkeypatch.setattr(node_agent, "HostKeyService", lambda: SimpleNamespace(
        verify_provider_attested=lambda *args, **kwargs: None
    ))

    import paramiko

    monkeypatch.setattr(paramiko, "Transport", FakeConnection)

    result = node_agent.fetch_usage(SimpleNamespace(pk=uuid4()))

    assert result == payload
    assert channel_state["socket"] == (("198.51.100.20", 22), 10)
    assert channel_state["start_timeout"] == 10
    assert channel_state["session_timeout"] == 10
    assert channel_state["timeout"] == 20
    assert channel_state["command"] == "sudo -n python3 -"
    assert channel_state["auth"] == ("ubuntu", "private-key-object")
    assert channel_state["shutdown_write"] is True
    assert channel_state["closed"] is True
    script = channel_state["script"]
    assert "xray' ,'api','statsquery'" not in script
    assert "xray','api','statsquery'" in script.replace(" ", "")
    assert "/var/lib/xray-manager/current-generation" in script
    assert "ExecMainStartTimestampMonotonic" in script
    assert "boot_id" in script
    assert "process_id" in script
    assert "sequence" in script
    assert "sampled_at" in script
