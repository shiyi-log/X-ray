"""Standalone SSH probe program. Requests and Xray client configs stay in memory.

Only opaque identifiers and measured booleans are written to stdout. The program
is sent as static source in the SSH command; credentials arrive through stdin.
"""

import hashlib
import json
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path


def service_identity():
    result = subprocess.run(
        [
            "systemctl", "show", "xray.service", "--property=ActiveState",
            "--property=MainPID", "--property=ExecMainStartTimestampMonotonic",
        ],
        capture_output=True, text=True, timeout=5, check=True,
    )
    fields = dict(
        line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
    )
    pid = int(fields.get("MainPID", "0"))
    started = int(fields.get("ExecMainStartTimestampMonotonic", "0"))
    if fields.get("ActiveState") != "active" or pid < 1 or started < 1:
        raise ValueError
    argv = [
        item.decode("utf-8", "strict")
        for item in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        if item
    ]
    if not argv or Path(argv[0]).name != "xray":
        raise ValueError
    try:
        config_path = argv[argv.index("-config") + 1]
    except (ValueError, IndexError):
        raise ValueError from None
    if (
        Path(config_path).name != "xray-config"
        or "/run/credentials/" not in config_path
    ):
        raise ValueError
    config_hash = hashlib.sha256(Path(config_path).read_bytes()).hexdigest()
    return {"pid": pid, "started": started, "config_hash": config_hash}


def exact(stream, size):
    data = b""
    while len(data) < size:
        chunk = stream.recv(size - len(data))
        if not chunk:
            raise EOFError
        data += chunk
    return data


def session_closed(stream, challenge):
    try:
        stream.sendall(challenge)
        return False if exact(stream, len(challenge)) == challenge else None
    except (EOFError, ConnectionResetError, BrokenPipeError):
        return True
    except OSError:
        return None


def stop_client(client):
    if client is None:
        return
    stream, process = client
    if stream is not None:
        stream.close()
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


class Probe:
    def __init__(
        self, binary, generation_path, config_path, journal_path, *, timeout_seconds=240
    ):
        self.binary = binary
        self.generation_path = Path(generation_path)
        self.config_path = Path(config_path)
        self.journal_path = Path(journal_path)
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(16)
        self.listener.settimeout(0.2)
        self.closed = threading.Event()
        self.expired = threading.Event()
        self.deadline = time.monotonic() + timeout_seconds
        self._deadline_thread = threading.Thread(target=self._watch_deadline, daemon=True)
        self.thread = threading.Thread(target=self.echo, daemon=True)
        self.thread.start()
        self.sessions = {}
        self.credentials = {}
        self.controls = {}
        self.control_credentials = {}
        self.scope = None
        self.baseline_service = None
        self.committed_service = None
        self.preapply_credentials_accepted = False
        self.expected_config_hash = None
        self.target_generation = None
        self.session_lock = threading.Lock()
        self._deadline_thread.start()

    def _watch_deadline(self):
        if not self.closed.wait(max(0, self.deadline - time.monotonic())):
            self.expired.set()
            with self.session_lock:
                sessions = tuple(self.sessions.values())
            for _session_id, session in sessions:
                session.close()

    def exchange_allowed(self):
        return not self.expired.is_set() and time.monotonic() < self.deadline

    def check_deadline(self):
        if not self.exchange_allowed():
            raise TimeoutError

    def generation(self):
        return int(self.generation_path.read_text().strip())

    def active_config(self, expected_generation, expected_hash=None):
        self.check_deadline()
        before = self.generation()
        raw = self.config_path.read_bytes()
        journal = json.loads(self.journal_path.read_text())
        after = self.generation()
        if (
            before != expected_generation or after != expected_generation
            or journal.get("generation") != expected_generation
            or journal.get("phase") != "COMMITTED"
            or journal.get("config_hash") != hashlib.sha256(raw).hexdigest()
            or (
                expected_hash is not None
                and hashlib.sha256(raw).hexdigest() != expected_hash
            )
        ):
            raise ValueError
        return json.loads(raw), hashlib.sha256(raw).hexdigest()

    @staticmethod
    def credential_configured(config, credential):
        for inbound in config.get("inbounds", []):
            if (
                inbound.get("protocol") != "shadowsocks"
                or inbound.get("port") != credential["port"]
            ):
                continue
            return any(
                client.get("method") == credential["method"]
                and client.get("password") == credential["password"]
                for client in inbound.get("settings", {}).get("clients", [])
            )
        return False

    def echo(self):
        def serve(stream):
            try:
                while data := stream.recv(4096):
                    stream.sendall(data)
            except OSError:
                pass
            finally:
                stream.close()

        while not self.closed.is_set():
            try:
                stream, _address = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(target=serve, args=(stream,), daemon=True).start()

    def connect(self, credential):
        """Return observed acceptance; timeouts remain unknown, never rejection."""
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            socks_port = reserved.getsockname()[1]
        config = {
            "log": {"loglevel": "none"},
            "inbounds": [{
                "listen": "127.0.0.1", "port": socks_port, "protocol": "socks",
                "settings": {"auth": "noauth", "udp": False},
            }],
            "outbounds": [{
                "protocol": "shadowsocks",
                "settings": {"servers": [{
                    "address": "127.0.0.1", "port": credential["port"],
                    "method": credential["method"], "password": credential["password"],
                }]},
            }],
        }
        process = subprocess.Popen(
            [self.binary, "run", "-format", "json", "-config", "/dev/stdin"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        stream = None
        established = False
        attempted = False
        try:
            self.check_deadline()
            process.stdin.write(json.dumps(config, separators=(",", ":")).encode())
            process.stdin.close()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    return None, None, attempted
                try:
                    stream = socket.create_connection(("127.0.0.1", socks_port), timeout=0.2)
                    break
                except OSError:
                    time.sleep(0.02)
            if stream is None:
                return None, None, attempted
            stream.settimeout(3)
            stream.sendall(b"\x05\x01\x00")
            if exact(stream, 2) != b"\x05\x00":
                return None, None, attempted
            port = self.listener.getsockname()[1]
            stream.sendall(b"\x05\x01\x00\x01\x7f\x00\x00\x01" + port.to_bytes(2, "big"))
            attempted = True
            header = exact(stream, 4)
            length = {1: 4, 4: 16}.get(header[3])
            if header[3] == 3:
                length = exact(stream, 1)[0]
            if length is None or header[1] != 0:
                return (False if header[1] != 0 else None), None, attempted
            exact(stream, length + 2)
            established = True
            challenge = secrets.token_bytes(24)
            stream.sendall(challenge)
            if exact(stream, len(challenge)) != challenge:
                return None, None, attempted
            client = (stream, process)
            stream = None
            process = None
            return True, client, attempted
        except (EOFError, ConnectionResetError, BrokenPipeError):
            return (False if established or attempted else None), None, attempted
        except (OSError, ValueError, KeyError, TypeError):
            return None, None, attempted
        finally:
            if process is not None:
                stop_client((stream, process))

    def control(self, credential):
        accepted, client, _attempted = self.connect(credential)
        stop_client(client)
        return accepted is True

    def capture(self, request):
        self.check_deadline()
        if self.scope is not None or self.generation() != request["generation"]:
            raise ValueError
        config, active_hash = self.active_config(request["generation"])
        initial_credentials = request["credentials"] + request["controls"]
        if not all(self.credential_configured(config, item) for item in initial_credentials):
            raise ValueError
        self.baseline_service = service_identity()
        if self.baseline_service["config_hash"] != active_hash:
            raise ValueError
        self.scope = (request["node_id"], request["operation_id"])
        controls = {item["protocol_id"]: item for item in request["controls"]}
        old_credentials_accepted = True
        for credential in request["credentials"]:
            control = controls[credential["protocol_id"]]
            if not self.control(control):
                raise ValueError
            accepted, client, _attempted = self.connect(credential)
            if accepted is not True:
                old_credentials_accepted = False
                raise ValueError
            ref = credential["credential_ref"]
            with self.session_lock:
                self.sessions[ref] = (credential["session_id"], Session(client, self))
            self.credentials[ref] = credential
            self.controls[ref] = control
        if self.generation() != request["generation"] or not self.exchange_allowed():
            raise ValueError
        self.control_credentials = {
            item["credential_ref"]: item for item in request["controls"]
        }
        self.preapply_credentials_accepted = old_credentials_accepted
        return {
            "ok": True, "generation": request["generation"],
            "sessions": {ref: value[0] for ref, value in self.sessions.items()},
        }

    def verify(self, request):
        self.check_deadline()
        ref = request["credential_ref"]
        with self.session_lock:
            session_id, session = self.sessions[ref]
        if (
            self.scope != (request["node_id"], request["operation_id"])
            or session_id != request["session_id"]
            or self.generation() != request["generation"]
        ):
            raise ValueError
        old_session_closed = session.verify_closed(
            self, expected_generation=request["generation"]
        )
        self.check_deadline()
        config, active_hash = self.active_config(
            request["generation"], self.expected_config_hash
        )
        revoked_configured = self.credential_configured(config, self.credentials[ref])
        control = self.controls[ref]
        control_configured = self.credential_configured(config, control)
        current_service = service_identity()
        service_stable = current_service == self.committed_service
        credential_config_matches = current_service["config_hash"] == active_hash
        control_before = self.control(self.controls[ref])
        accepted, fresh_client, attempted = self.connect(self.credentials[ref])
        stop_client(fresh_client)
        control_after = self.control(self.controls[ref])
        if revoked_configured or not control_configured:
            accepted = None
        if (
            self.generation() != request["generation"]
            or not self.exchange_allowed()
            or not service_stable
            or not credential_config_matches
        ):
            raise ValueError
        return {
            "ok": True, "credential_ref": ref, "session_id": session_id,
            "generation": request["generation"], "config_hash": active_hash,
            "accepted": accepted,
            "positive_control": control_before and control_after,
            "fresh_connection": attempted,
            "existing_session_closed": old_session_closed,
            "credential_excluded": not revoked_configured,
            "postapply_control_accepted": control_before and control_after,
            "credential_config_hash_matches": credential_config_matches,
        }

    def arm(self, request):
        self.check_deadline()
        if (
            self.scope != (request["node_id"], request["operation_id"])
            or self.generation() != request["generation"]
            or request["target_generation"] <= request["generation"]
            or request["sessions"]
            != {ref: value[0] for ref, value in self.sessions.items()}
        ):
            raise ValueError
        config, active_hash = self.active_config(request["generation"])
        if any(
            not self.credential_configured(config, credential)
            for credential in list(self.credentials.values())
            + list(self.control_credentials.values())
        ):
            raise ValueError
        if service_identity() != self.baseline_service:
            raise ValueError
        controls_accepted = all(
            self.control(credential)
            for credential in self.control_credentials.values()
        )
        if not controls_accepted:
            raise ValueError
        results = {}
        for ref, (session_id, session) in self.sessions.items():
            results[ref] = session.arm(self, expected_generation=request["generation"])
            if not results[ref]:
                break
        armed = len(results) == len(self.sessions) and all(results.values())
        if (
            self.generation() != request["generation"]
            or not self.exchange_allowed()
            or service_identity() != self.baseline_service
            or active_hash != self.baseline_service["config_hash"]
        ):
            raise ValueError
        self.preapply_credentials_accepted &= controls_accepted
        self.target_generation = request["target_generation"]
        return {
            "ok": True, "generation": request["generation"],
            "target_generation": self.target_generation,
            "armed": armed, "sessions": {
                ref: self.sessions[ref][0] for ref in results
            },
        }

    def commit(self, request):
        self.check_deadline()
        if (
            self.scope != (request["node_id"], request["operation_id"])
            or request["generation"] != self.target_generation
            or not isinstance(request["config_hash"], str)
            or len(request["config_hash"]) != 64
            or any(char not in "0123456789abcdef" for char in request["config_hash"])
        ):
            raise ValueError
        config, active_hash = self.active_config(
            request["generation"], request["config_hash"]
        )
        credential_excluded = all(
            not self.credential_configured(config, credential)
            for credential in self.credentials.values()
        )
        controls_configured = all(
            self.credential_configured(config, credential)
            for credential in self.control_credentials.values()
        )
        current_service = service_identity()
        process_identity_changed = (
            self.baseline_service is not None
            and current_service["pid"] != self.baseline_service["pid"]
            and current_service["started"] > self.baseline_service["started"]
        )
        credential_config_hash_matches = current_service["config_hash"] == active_hash
        if (
            self.generation() != request["generation"]
            or not self.exchange_allowed()
        ):
            raise ValueError
        self.expected_config_hash = active_hash
        self.committed_service = current_service
        return {
            "ok": True, "generation": request["generation"],
            "config_hash": active_hash,
            "credential_excluded": credential_excluded,
            "expected_config_applied": True,
            "service_restarted": process_identity_changed,
            "process_identity_changed": process_identity_changed,
            "credential_config_hash_matches": credential_config_hash_matches,
            "preapply_credentials_accepted": self.preapply_credentials_accepted,
            "positive_controls_configured": controls_configured,
        }

    def close(self):
        self.closed.set()
        with self.session_lock:
            sessions = tuple(self.sessions.values())
        for _session_id, session in sessions:
            session.close()
        self.sessions.clear()
        self.credentials.clear()
        self.controls.clear()
        self.control_credentials.clear()
        self.expected_config_hash = None
        self.committed_service = None
        self.listener.close()
        self.thread.join(timeout=1)
        if self._deadline_thread is not threading.current_thread():
            self._deadline_thread.join(timeout=1)


class Session:
    def __init__(self, client, probe):
        self.stream, self.process = client
        self.probe = probe
        self.stream.settimeout(3)
        self.stop_event = threading.Event()
        self.closed = threading.Event()
        self.unknown = threading.Event()
        self.armed_generation = None
        self.closed_generation = None
        self.thread = threading.Thread(target=self._keepalive, daemon=True)
        self.thread.start()

    def _keepalive(self):
        while not self.stop_event.is_set():
            if self.process.poll() is not None:
                self.unknown.set()
                return
            result = session_closed(self.stream, secrets.token_bytes(24))
            if result is True:
                try:
                    self.closed_generation = self.probe.generation()
                except (OSError, ValueError):
                    self.unknown.set()
                    return
                self.closed.set()
                return
            if result is None:
                self.unknown.set()
                return
            if self.stop_event.wait(2):
                return

    def arm(self, probe, *, expected_generation):
        self.stop_event.set()
        self.thread.join(timeout=4)
        try:
            probe.check_deadline()
            if (
                probe.generation() != expected_generation
                or self.process.poll() is not None
                or self.unknown.is_set()
                or self.closed.is_set()
            ):
                return False
        except (OSError, ValueError, TimeoutError):
            return False
        if session_closed(self.stream, secrets.token_bytes(24)) is not False:
            return False
        self.armed_generation = expected_generation
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._keepalive, daemon=True)
        self.thread.start()
        return True

    def verify_closed(self, probe, *, expected_generation):
        self.stop_event.set()
        self.thread.join(timeout=4)
        try:
            probe.check_deadline()
        except TimeoutError:
            return None
        if self.process.poll() is not None or self.unknown.is_set():
            return None
        if self.armed_generation is None:
            return None
        if self.closed.is_set():
            return True if self.closed_generation == expected_generation else None
        result = session_closed(self.stream, secrets.token_bytes(24))
        if self.process.poll() is not None or result is None:
            return None
        if result is False:
            return False
        try:
            self.closed_generation = probe.generation()
        except (OSError, ValueError):
            return None
        self.closed.set()
        return True if self.closed_generation == expected_generation else None

    def close(self):
        self.stop_event.set()
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=4)
        stop_client((self.stream, self.process))


def main():
    probe = Probe(
        sys.argv[1] if len(sys.argv) > 1 else "/usr/local/bin/xray",
        sys.argv[2] if len(sys.argv) > 2 else "/var/lib/xray-manager/current-generation",
        sys.argv[3] if len(sys.argv) > 3 else "/usr/local/etc/xray/config.json",
        sys.argv[4] if len(sys.argv) > 4 else "/var/lib/xray-manager/apply-journal.json",
    )
    try:
        for line in sys.stdin:
            if len(line) > 1024 * 1024:
                raise ValueError
            request = json.loads(line)
            if request["command"] == "close":
                break
            if request["command"] == "capture":
                response = probe.capture(request)
            elif request["command"] == "arm":
                response = probe.arm(request)
            elif request["command"] == "commit":
                response = probe.commit(request)
            elif request["command"] == "verify":
                response = probe.verify(request)
            else:
                raise ValueError
            print(json.dumps(response, separators=(",", ":")), flush=True)
    except Exception:
        print('{"ok":false,"error_code":"REVOCATION_PROBE_UNCONFIRMED"}', flush=True)
    finally:
        probe.close()


if __name__ == "__main__":
    main()
