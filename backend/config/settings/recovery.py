"""Fail-closed settings for an isolated restored database."""

from __future__ import annotations

import os

from .production import *  # noqa: F403
from .production import DATABASES

database_name = str(DATABASES["default"]["NAME"])
if not database_name.startswith("xray_restore_"):
    raise RuntimeError("recovery settings require an xray_restore_* database")
if os.getenv("XRAY_RECOVERY_CONFIRM") != "MAINTENANCE":
    raise RuntimeError("XRAY_RECOVERY_CONFIRM=MAINTENANCE is required")
