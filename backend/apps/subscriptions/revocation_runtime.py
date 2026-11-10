"""Measured revocation for the bootstrap Shadowsocks TCP configuration."""

from __future__ import annotations

import json
import shlex
import time
from pathlib import Path
from uuid import uuid4

from apps.nodes.execution_types import ProbeResult
from apps.nodes.executor import NodeExecutor
from common.errors import DomainError

from . import access
from .credentials import decrypt_material
from .models import NodeCredential

SUPPORTED_REVOCATION = {
    "protocol": "shadowsocks", "transport": "tcp", "method": "aes-128-gcm",
    "credential_scope": "profile", "requires_surviving_profile": True,
}


def _unconfirmed(code="REVOCATION_PROBE_UNCONFIRMED"):
    return DomainError(code, "撤回探测未获得完整可信证据", status_code=409)


def validate_request_profile(profile):
    credentials = (
        NodeCredential.objects.select_for_update(of=("self",))
        .filter(profile=profile, revoked_at__isnull=True)
        .select_related("node", "protocol")
        .order_by("node_id", "pk")
    )
    nodes = {}
    credential_refs = {}
    required_protocols = {}
    for credential in credentials:
        RevocationExecutor._credential(credential)
        nodes[credential.node_id] = credential.node
        credential_refs.setdefault(credential.node_id, set()).add(credential.pk)
        required_protocols.setdefault(credential.node_id, set()).add(
            credential.protocol_id
        )

    for node_id, protocol_ids in required_protocols.items():
        node = nodes[node_id]
        if node.desired_generation != node.applied_generation:
            raise _unconfirmed()
        controls = {
            credential.protocol_id
            for credential in access.active_node_credentials(
                node, excluded_credential_refs=credential_refs[node_id]
            )
            if credential.applied_generation == node.applied_generation
        }
        if not protocol_ids.issubset(controls):
            raise _unconfirmed("REVOCATION_POSITIVE_CONTROL_UNAVAILABLE")


class RevocationExecutor(NodeExecutor):
    def __init__(self):
        super().__init__(transport_factory=access.configured_factory())
        self.connection = None
        self.channel = None
        self.scope = None
        self.sessions = {}
        self.controls = set()
        self.generation = None
        self.expected_config_hash = ""
        self.apply_evidence = {}
        self.buffer = bytearray()

    @staticmethod
    def _credential(credential):
        protocol = credential.protocol
        material = decrypt_material(credential)
        if (
            protocol.protocol != "shadowsocks" or protocol.transport != "tcp"
            or protocol.tls_enabled or not protocol.enabled
            or credential.credential_scope != "profile"
            or material.get("method") != "aes-128-gcm"
        ):
            raise _unconfirmed("REVOCATION_PROTOCOL_UNSUPPORTED")
        return {
            "credential_ref": str(credential.pk), "protocol_id": str(protocol.pk),
            "port": protocol.port, "method": material["method"],
            "password": material["password"],
        }

    def _exchange(self, request):
        try:
            self.channel.sendall(json.dumps(request, separators=(",", ":")).encode() + b"\n")
            deadline = time.monotonic() + 90
            while b"\n" not in self.buffer:
                if time.monotonic() >= deadline or self.channel.exit_status_ready():
                    raise _unconfirmed()
                if self.channel.recv_ready():
                    chunk = self.channel.recv(4096)
                    if not chunk:
                        raise _unconfirmed()
                    self.buffer.extend(chunk)
                if self.channel.recv_stderr_ready():
                    self.channel.recv_stderr(4096)
                if len(self.buffer) > 65536:
                    raise _unconfirmed()
                time.sleep(0.01)
            raw, _, remaining = self.buffer.partition(b"\n")
            self.buffer = bytearray(remaining)
            response = json.loads(raw)
            if not isinstance(response, dict) or response.get("ok") is not True:
                raise _unconfirmed()
            return response
        except DomainError:
            raise
        except Exception:
            raise _unconfirmed() from None

    def capture_probe_sessions(self, node_id, *, credential_refs, operation_id):
        from apps.nodes.bootstrap_runtime import _ssh_transport
        from apps.nodes.models import ManagedNode

        node = ManagedNode.objects.get(pk=node_id)
        self._scope(node, operation_id)
        if self.scope is not None or node.desired_generation != node.applied_generation:
            raise _unconfirmed()
        credentials = list(
            NodeCredential.objects.filter(
                pk__in=credential_refs, node=node, revoked_at__isnull=True
            ).select_related("protocol")
        )
        if {credential.pk for credential in credentials} != set(credential_refs) or not credentials:
            raise _unconfirmed()
        removed = [self._credential(credential) for credential in credentials]
        surviving = access.active_node_credentials(node, excluded_credential_refs=credential_refs)
        controls = {}
        for credential in surviving:
            if credential.protocol_id in {item.protocol_id for item in credentials}:
                if credential.applied_generation != node.applied_generation:
                    continue
                controls[str(credential.protocol_id)] = self._credential(credential)
        if any(item["protocol_id"] not in controls for item in removed):
            raise _unconfirmed("REVOCATION_POSITIVE_CONTROL_UNAVAILABLE")
        self.scope = (node.pk, operation_id)
        self.sessions = {item["credential_ref"]: str(uuid4()) for item in removed}
        self.controls = {item["credential_ref"] for item in controls.values()}
        for item in removed:
            item["session_id"] = self.sessions[item["credential_ref"]]
        try:
            self.connection = _ssh_transport(node)
            self.channel = self.connection.open_session(timeout=15)
            self.channel.settimeout(1)
            program = Path(__file__).with_name("revocation_probe.py").read_text()
            self.channel.exec_command(
                "sudo -n python3 -u -c " + shlex.quote(program)
                + " /usr/local/bin/xray /var/lib/xray-manager/current-generation"
                + " /usr/local/etc/xray/config.json"
                + " /var/lib/xray-manager/apply-journal.json"
            )
            response = self._exchange({
                "command": "capture", "node_id": str(node.pk),
                "operation_id": str(operation_id), "generation": node.applied_generation,
                "credentials": removed, "controls": list(controls.values()),
            })
            if (
                response.get("generation") != node.applied_generation
                or response.get("sessions") != self.sessions
            ):
                raise _unconfirmed()
            return dict(self.sessions)
        except Exception:
            self.close()
            raise

    def apply_config(self, node_id, *, generation, config, operation_id, **kwargs):
        from apps.nodes.models import ManagedNode

        if self.scope != (node_id, operation_id) or not self.sessions:
            raise _unconfirmed()
        node = ManagedNode.objects.get(pk=node_id)
        if generation <= node.applied_generation:
            raise _unconfirmed()
        active = access.active_node_credentials(node, excluded_credential_refs=self.sessions)
        if not self.controls.issubset({str(credential.pk) for credential in active}):
            raise _unconfirmed("REVOCATION_POSITIVE_CONTROL_UNAVAILABLE")
        armed = self._exchange({
            "command": "arm", "node_id": str(node_id),
            "operation_id": str(operation_id), "generation": node.applied_generation,
            "target_generation": generation, "sessions": self.sessions,
        })
        if (
            armed.get("generation") != node.applied_generation
            or armed.get("target_generation") != generation
            or armed.get("armed") is not True
            or armed.get("sessions") != self.sessions
        ):
            raise _unconfirmed()
        result = super().apply_config(
            node_id, generation=generation,
            config=access.build_node_config(node, excluded_credential_refs=self.sessions),
            operation_id=operation_id, **kwargs,
        )
        if (
            result.applied_generation != generation
            or not result.service_restarted
            or len(result.config_hash) != 64
        ):
            raise _unconfirmed()
        committed = self._exchange({
            "command": "commit", "node_id": str(node_id),
            "operation_id": str(operation_id), "generation": generation,
            "config_hash": result.config_hash,
        })
        expected_evidence = (
            "credential_excluded", "expected_config_applied", "service_restarted",
            "process_identity_changed", "credential_config_hash_matches",
            "preapply_credentials_accepted", "positive_controls_configured",
        )
        if (
            committed.get("generation") != generation
            or committed.get("config_hash") != result.config_hash
            or any(committed.get(key) is not True for key in expected_evidence)
        ):
            raise _unconfirmed()
        self.generation = result.applied_generation
        self.expected_config_hash = result.config_hash
        self.apply_evidence = {
            key: committed[key] for key in expected_evidence
        }
        return result

    def probe(self, node_id, *, credential_ref, expect_accept, operation_id):
        if self.scope != (node_id, operation_id) or expect_accept or self.generation is None:
            raise _unconfirmed()
        ref = str(credential_ref)
        if ref not in self.sessions:
            raise _unconfirmed()
        response = self._exchange({
            "command": "verify", "node_id": str(node_id), "operation_id": str(operation_id),
            "credential_ref": ref, "session_id": self.sessions[ref], "generation": self.generation,
        })
        if (
            response.get("credential_ref") != ref
            or response.get("session_id") != self.sessions[ref]
            or response.get("generation") != self.generation
            or response.get("accepted") not in (True, False, None)
            or response.get("config_hash") != self.expected_config_hash
        ):
            raise _unconfirmed()
        evidence = {
            **self.apply_evidence,
            "postapply_control_accepted": response.get("postapply_control_accepted") is True,
            "credential_excluded": response.get("credential_excluded") is True,
        }
        return ProbeResult(
            accepted=response.get("accepted"),
            positive_control=response.get("positive_control") is True,
            fresh_connection=response.get("fresh_connection") is True,
            existing_session_closed=response.get("existing_session_closed") is True,
            evidence={
                **evidence, "session_id": self.sessions[ref],
                "generation": self.generation,
            },
        )

    def close(self):
        if self.channel is not None:
            try:
                self.channel.sendall(b'{"command":"close"}\n')
            except Exception:
                pass
            self.channel.close()
            self.channel = None
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        self.sessions.clear()
        self.controls.clear()
        self.buffer.clear()


def default_executor(_node):
    return RevocationExecutor()
