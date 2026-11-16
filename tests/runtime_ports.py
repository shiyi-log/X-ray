"""Shared fixtures loaded by both repository and backend pytest entry points."""

import os
import socket

import pytest

from port_pool import PortPool


@pytest.fixture
def xray_port_pool():
    with PortPool.from_value(os.getenv("XRAY_TEST_PORTS")) as pool:
        yield pool


@pytest.fixture(autouse=True)
def managed_loopback_binds(xray_port_pool, monkeypatch):
    """Keep in-process probe listeners within an explicit managed port list."""
    if xray_port_pool.ports is None:
        return
    original_bind = socket.socket.bind

    def bind(sock, address):
        if (
            sock.family == socket.AF_INET
            and isinstance(address, tuple)
            and address == ("127.0.0.1", 0)
        ):
            address = (address[0], xray_port_pool.allocate())
        return original_bind(sock, address)

    monkeypatch.setattr(socket.socket, "bind", bind)
