from __future__ import annotations

import hashlib
import json
import os
import secrets
import socket
import subprocess
import threading
import time
from contextlib import closing
from uuid import uuid4

import pytest

from apps.operations.models import Operation
from apps.subscriptions.credentials import CredentialService, decrypt_material
from apps.subscriptions.models import AccessProfile, RevocationNodeState
from apps.subscriptions.revocation import RevocationService

from .test_revocation import SuccessfulExecutor, UnconfirmedIsolation, make_preview


@pytest.fixture
def shadowsocks_profiles(ready_node, admin):
    from apps.nodes.models import NodeProtocol
    from apps.subscriptions.tokens import TokenService

    protocol = NodeProtocol.objects.create(
        node=ready_node,
        protocol="shadowsocks",
        port=8388,
        transport="tcp",
        credential_scope="profile",
    )
    target = AccessProfile.objects.create(name="withdrawn")
    survivor = AccessProfile.objects.create(name="retained")
    target_issued = TokenService.issue(target.pk)
    survivor_issued = TokenService.issue(survivor.pk)
    credentials = CredentialService.rotate(
        ready_node.pk,
        profile_ids=[target.pk, survivor.pk],
        protocol_ids=[protocol.pk],
    )
    ready_node.refresh_from_db()
    ready_node.applied_generation = ready_node.desired_generation
    ready_node.save(update_fields=["applied_generation", "updated_at"])
    for credential in credentials:
        credential.applied_generation = ready_node.applied_generation
        credential.save(update_fields=["applied_generation"])
    by_profile = {credential.profile_id: credential for credential in credentials}
    return (
        ready_node, target, survivor, by_profile[target.pk], by_profile[survivor.pk],
        target_issued, survivor_issued,
    )


def request_revocation(admin, profile):
    preview = make_preview(admin, profile)
    return RevocationService.request(
        profile.pk,
        key=uuid4(),
        preview_id=preview.pk,
        confirmation="REVOKE PROFILE",
        admin=admin,
        test_only_skip_runtime_preflight=True,
    )


@pytest.mark.parametrize("control_state", ["revoked", "stale"], ids=["missing", "unapplied"])
@pytest.mark.django_db
def test_profile_revocation_request_rejects_missing_positive_control(
    admin, shadowsocks_profiles, control_state
):
    from django.utils import timezone

    from apps.subscriptions.models import NodeCredential
    from common.errors import DomainError

    (
        _node,
        profile,
        _survivor,
        _target_credential,
        survivor_credential,
        _target_link,
        _survivor_link,
    ) = shadowsocks_profiles
    updates = {"revoked_at": timezone.now()} if control_state == "revoked" else {
        "applied_generation": 0
    }
    NodeCredential.objects.filter(pk=survivor_credential.pk).update(**updates)
    preview = make_preview(admin, profile)

    with pytest.raises(DomainError) as error:
        RevocationService.request(
            profile.pk,
            key=uuid4(),
            preview_id=preview.pk,
            confirmation="REVOKE PROFILE",
            admin=admin,
        )

    assert error.value.code == "REVOCATION_POSITIVE_CONTROL_UNAVAILABLE"
    profile.refresh_from_db()
    assert profile.status == "ACTIVE"
    assert not Operation.objects.filter(
        kind="subscription.revoke", target_id=profile.pk
    ).exists()


@pytest.mark.django_db
def test_profile_revocation_request_accepts_current_positive_control(
    admin, shadowsocks_profiles
):
    from apps.subscriptions.tokens import TokenGone, TokenService

    node, profile, survivor, target_credential, _survivor_credential, target_link, survivor_link = (
        shadowsocks_profiles
    )
    preview = make_preview(admin, profile)
    operation = RevocationService.request(
        profile.pk,
        key=uuid4(),
        preview_id=preview.pk,
        confirmation="REVOKE PROFILE",
        admin=admin,
        test_only_skip_runtime_preflight=False,
    )

    profile.refresh_from_db()
    survivor.refresh_from_db()
    assert profile.status == "REVOKING"
    assert survivor.status == "ACTIVE"
    assert RevocationNodeState.objects.get(operation=operation, node=node).credential_refs == [
        str(target_credential.pk)
    ]
    with pytest.raises(TokenGone):
        TokenService.resolve(target_link.raw_token)
    assert TokenService.resolve(survivor_link.raw_token).profile_id == survivor.pk


class ProbeChannel:
    def __init__(self, generation):
        self.generation = generation
        self.output = bytearray()
        self.requests = []
        self.command = ""
        self.closed = False

    def settimeout(self, _timeout):
        pass

    def exec_command(self, command):
        self.command = command

    def sendall(self, payload):
        request = json.loads(payload)
        self.requests.append(request)
        if request["command"] == "capture":
            response = {
                "ok": True,
                "generation": self.generation,
                "sessions": {
                    item["credential_ref"]: item["session_id"]
                    for item in request["credentials"]
                },
            }
        elif request["command"] == "arm":
            response = {
                "ok": True,
                "generation": request["generation"],
                "target_generation": request["target_generation"],
                "armed": True,
                "sessions": request["sessions"],
            }
        elif request["command"] == "commit":
            self.config_hash = request["config_hash"]
            response = {
                "ok": True,
                "generation": request["generation"],
                "config_hash": request["config_hash"],
                "credential_excluded": True,
                "expected_config_applied": True,
                "service_restarted": True,
                "process_identity_changed": True,
                "credential_config_hash_matches": True,
                "preapply_credentials_accepted": True,
                "positive_controls_configured": True,
            }
        else:
            response = {
                "ok": True,
                "session_id": request["session_id"],
                "credential_ref": request["credential_ref"],
                "generation": request["generation"],
                "accepted": False,
                "positive_control": True,
                "fresh_connection": True,
                "existing_session_closed": True,
                "credential_excluded": True,
                "postapply_control_accepted": True,
                "credential_config_hash_matches": True,
                "config_hash": getattr(self, "config_hash", ""),
            }
        self.output.extend(json.dumps(response).encode() + b"\n")

    def recv_ready(self):
        return bool(self.output)

    def recv(self, size):
        output = bytes(self.output[:size])
        del self.output[:size]
        return output

    def recv_stderr_ready(self):
        return False

    def exit_status_ready(self):
        return False

    def close(self):
        self.closed = True


class ProbeConnection:
    def __init__(self, channel):
        self.channel = channel
        self.closed = False

    def open_session(self, **_kwargs):
        return self.channel

    def close(self):
        self.closed = True


@pytest.mark.django_db
def test_default_revocation_executes_real_config_and_keeps_other_profile(
    admin, shadowsocks_profiles, monkeypatch, caplog
):
    from apps.nodes import bootstrap_runtime
    from apps.subscriptions import access

    node, target, survivor, removed, retained, target_link, survivor_link = shadowsocks_profiles
    channel = ProbeChannel(node.applied_generation)
    connection = ProbeConnection(channel)
    monkeypatch.setattr(bootstrap_runtime, "_ssh_transport", lambda _node: connection)
    applied = []

    class Transport:
        def apply(self, request):
            assert [item["command"] for item in channel.requests] == ["capture", "arm"]
            applied.append(request)
            return {
                "ok": True,
                "applied_generation": request["generation"],
                "config_test_passed": True,
                "service_restarted": True,
                "rollback_performed": False,
                "config_hash": hashlib.sha256(
                    json.dumps(request["config"], separators=(",", ":")).encode()
                ).hexdigest(),
            }

    monkeypatch.setattr(access, "configured_factory", lambda: lambda _node: Transport())
    operation = request_revocation(admin, target)
    result = RevocationService(
        lifecycle_factory=UnconfirmedIsolation,
        invalidate_node=lambda _node_id: None,
    ).run(operation.pk)

    assert result.status == "SUCCEEDED", result.error_code
    assert len(applied) == 1
    config = applied[0]["config"]
    assert "inbounds" in config and "credentials" not in config
    serialized = json.dumps(config)
    assert decrypt_material(removed)["password"] not in serialized
    assert decrypt_material(retained)["password"] in serialized
    removed.refresh_from_db()
    retained.refresh_from_db()
    survivor.refresh_from_db()
    assert removed.revoked_at is not None
    assert retained.revoked_at is None
    assert retained.applied_generation == applied[0]["generation"]
    assert survivor.status == "ACTIVE"
    from apps.subscriptions.tokens import TokenGone, TokenService

    with pytest.raises(TokenGone):
        TokenService.resolve(target_link.raw_token)
    assert TokenService.resolve(survivor_link.raw_token).profile_id == survivor.pk
    assert channel.closed and connection.closed
    assert channel.requests[0]["command"] == "capture"
    assert [item["command"] for item in channel.requests] == [
        "capture", "arm", "commit", "verify", "close",
    ]
    for credential in (removed, retained):
        secret = decrypt_material(credential)["password"]
        assert secret not in channel.command
        assert secret not in caplog.text
        assert secret not in json.dumps(result.result)
        assert secret not in json.dumps(list(result.steps.values("evidence", "result")))


@pytest.mark.django_db
def test_lost_revocation_fence_stops_without_quarantine_or_finalization(
    admin, revocable_profile
):
    from common.errors import DomainError

    _issued, profile, node, credential = revocable_profile
    operation = request_revocation(admin, profile)
    quarantined = []

    class StolenExecutor(SuccessfulExecutor):
        def capture_probe_sessions(self, *args, **kwargs):
            Operation.objects.filter(pk=operation.pk).update(
                lease_owner="replacement-worker", lease_fence=50
            )
            return super().capture_probe_sessions(*args, **kwargs)

    class Isolation:
        def quarantine(self, *_args, **_kwargs):
            quarantined.append(True)

    executor = StolenExecutor()
    with pytest.raises(DomainError) as error:
        RevocationService(
            executor_factory=lambda _node: executor,
            lifecycle_factory=Isolation,
            invalidate_node=lambda _node_id: None,
        ).run(operation.pk)
    assert error.value.code == "STALE_OPERATION_FENCE"
    operation.refresh_from_db()
    state = RevocationNodeState.objects.get(operation=operation, node=node)
    credential.refresh_from_db()
    assert operation.lease_owner == "replacement-worker"
    assert operation.lease_fence == 50
    assert operation.status == "RUNNING"
    assert state.status == "REQUESTED"
    assert credential.revoked_at is None
    assert not executor.applied
    assert not quarantined


@pytest.mark.django_db
def test_live_revocation_lease_rejects_duplicate_worker(admin, revocable_profile):
    from apps.operations.claims import claim_operation
    from common.errors import DomainError

    _issued, profile, _node, _credential = revocable_profile
    operation = request_revocation(admin, profile)
    claim_operation(operation.pk, worker_id="first-worker", lease_seconds=240)
    executor = SuccessfulExecutor()
    with pytest.raises(DomainError) as error:
        RevocationService(executor_factory=lambda _node: executor).run(operation.pk)
    assert error.value.code == "OPERATION_LEASED"
    assert not executor.captured


def test_session_probe_counts_only_observed_eof_as_closed():
    from apps.subscriptions.revocation_probe import session_closed

    left, right = socket.socketpair()
    challenge = b"challenge"
    try:
        right.sendall(b"different")
        assert session_closed(left, challenge) is None
    finally:
        left.close()
        right.close()

    left, right = socket.socketpair()
    try:
        def echo_once():
            right.sendall(right.recv(len(challenge)))

        responder = threading.Thread(target=echo_once)
        responder.start()
        assert session_closed(left, challenge) is False
        responder.join(timeout=1)
    finally:
        left.close()
        right.close()

    left, right = socket.socketpair()
    right.close()
    try:
        assert session_closed(left, challenge) is True
    finally:
        left.close()

    left, right = socket.socketpair()
    left.settimeout(0.01)
    try:
        assert session_closed(left, challenge) is None
    finally:
        left.close()
        right.close()


def test_probe_deadline_cleans_remote_clients(tmp_path):
    from apps.subscriptions.revocation_probe import Probe

    probe = Probe(
        "unused", tmp_path / "generation", tmp_path / "config.json",
        tmp_path / "journal.json", timeout_seconds=0.05,
    )
    try:
        time.sleep(0.1)
        assert probe.expired.is_set()
        assert probe.exchange_allowed() is False
    finally:
        probe.close()


def test_probe_refuses_to_arm_revocation_when_surviving_control_is_down(
    tmp_path, monkeypatch
):
    from apps.subscriptions import revocation_probe
    from apps.subscriptions.revocation_probe import Probe

    baseline = {"pid": 10, "started": 100, "config_hash": "a" * 64}
    probe = Probe(
        "unused", tmp_path / "generation", tmp_path / "config", tmp_path / "journal"
    )
    probe.scope = ("node-1", "operation-1")
    probe.baseline_service = baseline
    probe.generation = lambda: 1
    probe.active_config = lambda _generation: ({"inbounds": []}, "a" * 64)
    probe.credential_configured = lambda _config, _credential: True
    probe.control = lambda _credential: False
    monkeypatch.setattr(revocation_probe, "service_identity", lambda: baseline)

    class Session:
        arm_calls = 0

        def arm(self, _probe, *, expected_generation):
            self.arm_calls += 1
            return expected_generation == 1

        def close(self):
            pass

    session = Session()
    probe.sessions = {"credential-1": ("session-1", session)}
    probe.credentials = {"credential-1": {"credential_ref": "credential-1"}}
    probe.control_credentials = {"control-1": {"credential_ref": "control-1"}}

    try:
        with pytest.raises(ValueError):
            probe.arm(
                {
                    "node_id": "node-1",
                    "operation_id": "operation-1",
                    "generation": 1,
                    "target_generation": 2,
                    "sessions": {"credential-1": "session-1"},
                }
            )
        assert session.arm_calls == 0
    finally:
        probe.close()


def test_session_closed_before_apply_cannot_be_armed(tmp_path):
    from apps.subscriptions.revocation_probe import Probe, Session

    generation = tmp_path / "generation"
    generation.write_text("1")
    probe = Probe(
        "unused", generation, tmp_path / "config", tmp_path / "journal",
        timeout_seconds=1,
    )

    class Process:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    left, right = socket.socketpair()
    session = Session((left, Process()), probe)
    right.close()
    try:
        deadline = time.monotonic() + 1
        while not session.closed.is_set() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert session.arm(probe, expected_generation=1) is False
    finally:
        session.close()
        probe.close()


def test_service_identity_hashes_the_running_loadcredential_config(tmp_path, monkeypatch):
    from hashlib import sha256
    from pathlib import Path
    from types import SimpleNamespace

    from apps.subscriptions import revocation_probe

    credential = tmp_path / "run" / "credentials" / "xray.service" / "xray-config"
    credential.parent.mkdir(parents=True)
    credential.write_bytes(b"config")
    original_read_bytes = Path.read_bytes

    def read_bytes(path):
        if path == Path("/proc/42/cmdline"):
            return (
                b"/usr/local/bin/xray\0run\0-config\0"
                + str(credential).encode()
                + b"\0-format\0json\0"
            )
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(
        revocation_probe.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=(
                "ActiveState=active\nMainPID=42\n"
                "ExecMainStartTimestampMonotonic=123456\n"
            )
        ),
    )

    assert revocation_probe.service_identity() == {
        "pid": 42,
        "started": 123456,
        "config_hash": sha256(b"config").hexdigest(),
    }


@pytest.mark.django_db
def test_probe_generation_race_never_rolls_node_back(
    admin, revocable_profile
):
    from apps.nodes.models import ManagedNode

    _issued, profile, node, credential = revocable_profile
    operation = request_revocation(admin, profile)

    class GenerationRaceExecutor(SuccessfulExecutor):
        def probe(self, *args, **kwargs):
            ManagedNode.objects.filter(pk=node.pk).update(desired_generation=77)
            return super().probe(*args, **kwargs)

    executor = GenerationRaceExecutor()
    result = RevocationService(
        executor_factory=lambda _node: executor,
        lifecycle_factory=UnconfirmedIsolation,
        invalidate_node=lambda _node_id: None,
    ).run(operation.pk)
    node.refresh_from_db()
    credential.refresh_from_db()
    assert node.desired_generation == 77
    assert node.applied_generation != 77
    assert result.status == "PARTIALLY_SUCCEEDED"
    assert credential.revoked_at is None


@pytest.mark.django_db
def test_no_surviving_profile_fails_closed_before_opening_probe_transport(
    admin, revocable_profile, monkeypatch
):
    from apps.nodes import bootstrap_runtime
    from apps.subscriptions.tokens import TokenGone, TokenService

    issued, profile, _node, credential = revocable_profile
    operation = request_revocation(admin, profile)
    monkeypatch.setattr(
        bootstrap_runtime, "_ssh_transport",
        lambda _node: pytest.fail("transport opened without a positive-control profile"),
    )
    result = RevocationService(
        lifecycle_factory=UnconfirmedIsolation,
        invalidate_node=lambda _node_id: None,
    ).run(operation.pk)
    credential.refresh_from_db()
    assert result.status == "PARTIALLY_SUCCEEDED"
    assert credential.revoked_at is None
    with pytest.raises(TokenGone):
        TokenService.resolve(issued.raw_token)


@pytest.mark.django_db
def test_apply_without_installer_config_hash_never_commits_probe_evidence(
    admin, shadowsocks_profiles, monkeypatch
):
    from apps.subscriptions import access
    from apps.subscriptions.revocation_runtime import RevocationExecutor
    from common.errors import DomainError

    node, target, _survivor, removed, retained, _target_link, _survivor_link = (
        shadowsocks_profiles
    )
    operation = request_revocation(admin, target)
    commands = []

    class Transport:
        def apply(self, request):
            return {
                "ok": True,
                "applied_generation": request["generation"],
                "config_test_passed": True,
                "service_restarted": True,
                "rollback_performed": False,
            }

    monkeypatch.setattr(access, "configured_factory", lambda: lambda _node: Transport())
    executor = RevocationExecutor()
    executor.scope = (node.pk, operation.pk)
    executor.sessions = {str(removed.pk): "session-old"}
    executor.controls = {str(retained.pk)}

    def exchange(request):
        commands.append(request["command"])
        return {
            "generation": request["generation"],
            "target_generation": request["target_generation"],
            "armed": True,
            "sessions": request["sessions"],
        }

    monkeypatch.setattr(executor, "_exchange", exchange)
    with pytest.raises(DomainError) as error:
        executor.apply_config(
            node.pk,
            generation=node.applied_generation + 1,
            config={},
            operation_id=operation.pk,
        )
    assert getattr(error.value, "code", "") == "REVOCATION_PROBE_UNCONFIRMED"
    assert commands == ["arm"]


@pytest.mark.django_db
def test_unsupported_protocol_is_rejected_before_revocation_side_effects(
    admin, revocable_profile
):
    from apps.subscriptions.models import RevocationNodeState
    from apps.subscriptions.tokens import TokenService
    from common.errors import DomainError

    issued, profile, node, _credential = revocable_profile
    preview = make_preview(admin, profile)

    with pytest.raises(DomainError) as error:
        RevocationService.request(
            profile.pk,
            key=uuid4(),
            preview_id=preview.pk,
            confirmation="REVOKE PROFILE",
            admin=admin,
        )

    assert error.value.code == "REVOCATION_PROTOCOL_UNSUPPORTED"
    profile.refresh_from_db()
    node.refresh_from_db()
    assert profile.status == "ACTIVE"
    assert profile.publishing_frozen is False
    assert node.security_state == "OPEN"
    assert TokenService.resolve(issued.raw_token).pk == issued.subscription_id
    assert not Operation.objects.filter(
        kind="subscription.revoke", target_id=profile.pk
    ).exists()
    assert not RevocationNodeState.objects.filter(node=node).exists()


def test_fixed_xray_shadowsocks_revocation_probe(tmp_path, monkeypatch):
    binary = os.getenv("XRAY_TEST_BINARY")
    if not binary or not os.path.isfile(binary):
        pytest.skip("fixed Xray binary is not configured")
    from apps.subscriptions import revocation_probe
    from apps.subscriptions.revocation_probe import Probe

    with closing(socket.socket()) as listener:
        listener.bind(("127.0.0.1", 0))
        server_port = listener.getsockname()[1]
    old_password = secrets.token_urlsafe(24)
    control_password = secrets.token_urlsafe(24)
    generation_path = tmp_path / "generation"
    config_path = tmp_path / "config.json"
    journal_path = tmp_path / "apply-journal.json"

    def prepare_server(passwords, generation):
        config = {
            "log": {"loglevel": "none"},
            "inbounds": [{
                "listen": "127.0.0.1", "port": server_port,
                "protocol": "shadowsocks",
                "settings": {"network": "tcp", "clients": [
                    {"method": "aes-128-gcm", "password": value, "email": str(index)}
                    for index, value in enumerate(passwords)
                ]},
            }],
            "outbounds": [{"protocol": "freedom"}],
        }
        raw = json.dumps(config, separators=(",", ":")).encode()
        config_path.write_bytes(raw)
        generation_path.write_text(str(generation))
        journal_path.write_text(json.dumps({
            "generation": generation, "config_hash": hashlib.sha256(raw).hexdigest(),
            "phase": "COMMITTED",
        }))
        server_file = tmp_path / f"server-{generation}.json"
        server_file.write_bytes(raw)
        return server_file

    def run_server(server_file):
        process = subprocess.Popen(
            [binary, "run", "-config", str(server_file)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("local fixed Xray server exited before readiness")
            with closing(socket.socket()) as probe_socket:
                probe_socket.settimeout(0.1)
                if probe_socket.connect_ex(("127.0.0.1", server_port)) == 0:
                    break
            time.sleep(0.02)
        else:
            pytest.fail("local fixed Xray server did not become ready")
        return process

    server = run_server(prepare_server([old_password, control_password], 1))
    service = {
        "pid": 100,
        "started": 1000,
        "config_hash": hashlib.sha256(config_path.read_bytes()).hexdigest(),
    }
    monkeypatch.setattr(revocation_probe, "service_identity", lambda: dict(service))
    probe = Probe(binary, generation_path, config_path, journal_path)
    old = {
        "credential_ref": "old-ref", "session_id": "session-old", "protocol_id": "ss",
        "port": server_port, "method": "aes-128-gcm", "password": old_password,
    }
    control = {
        "credential_ref": "control-ref", "session_id": "session-control", "protocol_id": "ss",
        "port": server_port, "method": "aes-128-gcm", "password": control_password,
    }
    try:
        captured = probe.capture({
            "command": "capture", "node_id": "node", "operation_id": "operation",
            "generation": 1, "credentials": [old], "controls": [control],
        })
        assert captured["sessions"] == {"old-ref": "session-old"}
        armed = probe.arm({
            "command": "arm", "node_id": "node", "operation_id": "operation",
            "generation": 1, "target_generation": 2,
            "sessions": {"old-ref": "session-old"},
        })
        assert armed["armed"] is True
        old_session = probe.sessions["old-ref"][1]
        old_client_process = old_session.process
        next_server_file = prepare_server([control_password], 2)
        server.terminate()
        server.wait(timeout=5)
        server = run_server(next_server_file)
        service.update(
            pid=101,
            started=2000,
            config_hash=hashlib.sha256(config_path.read_bytes()).hexdigest(),
        )
        committed = probe.commit({
            "command": "commit", "node_id": "node", "operation_id": "operation",
            "generation": 2, "config_hash": service["config_hash"],
        })
        assert committed["credential_excluded"] is True
        assert committed["service_restarted"] is True
        assert committed["credential_config_hash_matches"] is True
        accepted, direct_client, attempted = probe.connect(old)
        from apps.subscriptions.revocation_probe import stop_client

        stop_client(direct_client)
        assert attempted is True
        assert accepted in (False, None)
        result = probe.verify({
            "command": "verify", "node_id": "node", "operation_id": "operation",
            "credential_ref": "old-ref", "session_id": "session-old", "generation": 2,
        })
        assert result["accepted"] is accepted or result["accepted"] is None
        assert result["positive_control"] is True
        assert result["fresh_connection"] is True
        assert result["existing_session_closed"] is True
        assert result["credential_excluded"] is True
        from apps.nodes.execution_types import ProbeResult
        from apps.subscriptions.verification import verified_revoked

        assert verified_revoked(ProbeResult(
            accepted=result["accepted"],
            positive_control=result["positive_control"],
            fresh_connection=result["fresh_connection"],
            existing_session_closed=result["existing_session_closed"],
            evidence={
                "credential_excluded": result["credential_excluded"],
                "expected_config_applied": committed["expected_config_applied"],
                "service_restarted": committed["service_restarted"],
                "process_identity_changed": committed["process_identity_changed"],
                "credential_config_hash_matches": result["credential_config_hash_matches"],
                "preapply_credentials_accepted": committed[
                    "preapply_credentials_accepted"
                ],
                "postapply_control_accepted": result[
                    "postapply_control_accepted"
                ],
            },
        )) is True
    finally:
        probe.close()
        assert old_client_process.poll() is not None
        server.terminate()
        server.wait(timeout=5)


def test_fixed_xray_blackhole_timeout_stays_unknown(tmp_path):
    binary = os.getenv("XRAY_TEST_BINARY")
    if not binary or not os.path.isfile(binary):
        pytest.skip("fixed Xray binary is not configured")
    from apps.subscriptions.revocation_probe import Probe, stop_client

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    port = listener.getsockname()[1]
    accepted_sockets = []

    def accept_connection():
        listener.settimeout(5)
        try:
            stream, _address = listener.accept()
            accepted_sockets.append(stream)
            time.sleep(4)
        except OSError:
            pass

    accepting = threading.Thread(target=accept_connection, daemon=True)
    accepting.start()
    probe = Probe(
        binary, tmp_path / "generation", tmp_path / "config", tmp_path / "journal",
        timeout_seconds=20,
    )
    try:
        result, client, attempted = probe.connect({
            "port": port, "method": "aes-128-gcm", "password": secrets.token_urlsafe(24),
        })
        stop_client(client)
        assert attempted is True
        assert result is None
    finally:
        probe.close()
        listener.close()
        for stream in accepted_sockets:
            stream.close()
        accepting.join(timeout=1)
