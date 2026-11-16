"""Test-only loopback ports, restricted to the managed list when configured."""

from __future__ import annotations

import fcntl
import os
import socket
import tempfile
from contextlib import closing
from pathlib import Path


class PortPool:
    def __init__(self, ports, lock_dir):
        self.ports = ports
        self.lock_dir = Path(lock_dir)
        self._leases = {}

    @classmethod
    def from_value(cls, value, *, lock_dir=None):
        ports = None
        if value is not None:
            parts = value.split(",")
            if not all(part.strip().isascii() and part.strip().isdecimal() for part in parts):
                raise ValueError("XRAY_TEST_PORTS must be a comma-separated list of ports")
            ports = tuple(int(part.strip()) for part in parts)
            if any(not 1 <= port <= 65535 for port in ports) or len(set(ports)) != len(ports):
                raise ValueError("XRAY_TEST_PORTS must contain unique ports from 1 to 65535")
        if lock_dir is None:
            lock_dir = Path(tempfile.gettempdir()) / f"xray-test-port-locks-{os.getuid()}"
        return cls(ports, lock_dir)

    @staticmethod
    def _available(port):
        try:
            with (
                closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as stream,
                closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as datagram,
            ):
                stream.bind(("127.0.0.1", port))
                datagram.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False

    def allocate(self, *, excluded=()):
        self.lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        candidates = self.ports if self.ports is not None else (None for _ in range(100))
        for candidate in candidates:
            if candidate is None:
                with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as stream:
                    stream.bind(("127.0.0.1", 0))
                    candidate = stream.getsockname()[1]
            if candidate in self._leases or candidate in excluded:
                continue
            lease = (self.lock_dir / f"{candidate}.lock").open("a")
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if not self._available(candidate):
                    lease.close()
                    continue
            except (BlockingIOError, OSError):
                lease.close()
                continue
            self._leases[candidate] = lease
            return candidate
        label = "XRAY_TEST_PORTS exhausted" if self.ports is not None else "No free local test port"
        raise OSError(f"{label}; check TCP/UDP occupancy and concurrent test leases")

    def close(self):
        for lease in self._leases.values():
            lease.close()
        self._leases.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_exception):
        self.close()
