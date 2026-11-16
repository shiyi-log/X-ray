"""Shared local runtime ports for backend and delivery integration tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "tests"))
from runtime_ports import managed_loopback_binds, xray_port_pool  # noqa: E402, F401
