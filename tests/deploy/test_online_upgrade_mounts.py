from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPGRADE_ROOT = "/var/lib/xray/upgrade"


def production_services():
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(ROOT / "deploy/compose/config.example.env"),
            "-f",
            str(ROOT / "deploy/compose/production.yml"),
            "config",
            "--format",
            "json",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)["services"]


def test_upgrade_api_can_write_requests_but_cannot_change_catalog_or_results():
    service = production_services()["admin-api"]
    mounts = {item["target"]: item for item in service["volumes"]}
    assert mounts[UPGRADE_ROOT]["read_only"] is True
    request_mount = mounts[UPGRADE_ROOT + "/requests"]
    assert request_mount.get("read_only", False) is False
    assert request_mount["source"] == UPGRADE_ROOT + "/requests"
    assert {
        target for target, item in mounts.items() if not item.get("read_only", False)
    } == {UPGRADE_ROOT + "/requests"}
    # Compose v2 omits false defaults in its rendered JSON; v5 preserves them.
    assert all(
        item.get("bind", {}).get("create_host_path", False) is False
        for item in mounts.values()
    )


def test_upgrade_queue_is_private_to_admin_api_without_host_control_mounts():
    services = production_services()
    for name, service in services.items():
        mounts = service.get("volumes", [])
        assert not any(
            str(item.get("source", "")).endswith("docker.sock") for item in mounts
        )
        if name != "admin-api":
            assert not any(
                str(item["target"]).startswith(UPGRADE_ROOT) for item in mounts
            )
