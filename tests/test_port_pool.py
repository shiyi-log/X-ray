from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from port_pool import PortPool


@pytest.mark.parametrize(
    "value", ["", " ", "0", "65536", "12-20", "1234,", "1234,1234", "abc"]
)
def test_explicit_ports_reject_invalid_configuration(value, tmp_path):
    with pytest.raises(ValueError, match="XRAY_TEST_PORTS"):
        PortPool.from_value(value, lock_dir=tmp_path)


def test_explicit_pool_never_falls_back_after_exhaustion(tmp_path, monkeypatch):
    attempts = []
    monkeypatch.setattr(PortPool, "_available", staticmethod(lambda port: attempts.append(port) or True))
    with PortPool.from_value("56001,56002", lock_dir=tmp_path) as pool:
        assert pool.allocate() == 56001
        assert pool.allocate() == 56002
        with pytest.raises(OSError, match="XRAY_TEST_PORTS exhausted"):
            pool.allocate()
    assert attempts == [56001, 56002]


def test_pool_skips_occupied_tcp_or_udp_port(tmp_path, monkeypatch):
    monkeypatch.setattr(PortPool, "_available", staticmethod(lambda port: port == 56002))
    with PortPool.from_value("56001,56002", lock_dir=tmp_path) as pool:
        assert pool.allocate() == 56002


def test_port_leases_are_exclusive_until_pool_closes(tmp_path, monkeypatch):
    monkeypatch.setattr(PortPool, "_available", staticmethod(lambda port: True))
    with PortPool.from_value("56001", lock_dir=tmp_path) as first:
        assert first.allocate() == 56001
        with PortPool.from_value("56001", lock_dir=tmp_path) as second:
            with pytest.raises(OSError, match="exhausted"):
                second.allocate()
    with PortPool.from_value("56001", lock_dir=tmp_path) as third:
        assert third.allocate() == 56001


def test_port_lease_is_shared_with_another_python_process(tmp_path, monkeypatch):
    monkeypatch.setattr(PortPool, "_available", staticmethod(lambda port: True))
    script = """
import sys
from port_pool import PortPool
PortPool._available = staticmethod(lambda port: True)
with PortPool.from_value('56001', lock_dir=sys.argv[1]) as pool:
    try:
        pool.allocate()
    except OSError:
        sys.exit(3)
"""
    with PortPool.from_value("56001", lock_dir=tmp_path) as pool:
        assert pool.allocate() == 56001
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path)],
            cwd=Path(__file__).parent,
            capture_output=True,
            check=False,
        )
    assert result.returncode == 3, result.stderr


def test_availability_checks_tcp_and_udp_and_rejects_occupied_udp(monkeypatch):
    import socket

    calls = []

    class FakeSocket:
        def __init__(self, kind):
            self.kind = kind

        def bind(self, address):
            calls.append((self.kind, address))
            if self.kind == socket.SOCK_DGRAM:
                raise OSError("occupied UDP")

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", lambda _family, kind: FakeSocket(kind))
    assert not PortPool._available(56001)
    assert calls == [
        (socket.SOCK_STREAM, ("127.0.0.1", 56001)),
        (socket.SOCK_DGRAM, ("127.0.0.1", 56001)),
    ]


def test_explicit_pool_excludes_reserved_ports(tmp_path, monkeypatch):
    attempts = []
    monkeypatch.setattr(PortPool, "_available", staticmethod(lambda port: attempts.append(port) or True))
    with PortPool.from_value("56001,56002", lock_dir=tmp_path) as pool:
        assert pool.allocate(excluded={56001}) == 56002
    assert attempts == [56002]
