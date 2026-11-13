from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("service_name", "target", "size"),
    [("database-bootstrap", "/tmp", "16384k"), ("redis", "/data", "65536k")],
)
def test_production_tmpfs_options_reach_the_container_as_one_mount(service_name, target, size):
    image = os.getenv("XRAY_BACKEND_TEST_IMAGE")
    if not image:
        pytest.skip("XRAY_BACKEND_TEST_IMAGE is required for the tmpfs mount gate")
    config = subprocess.run(
        [
            "docker", "compose", "--profile", "release", "--env-file",
            str(ROOT / "deploy/compose/config.example.env"),
            "--file", str(ROOT / "deploy/compose/production.yml"),
            "config", "--format", "json",
        ],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    service = json.loads(config.stdout)["services"][service_name]
    command = [
        "docker", "run", "--rm", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
    ]
    for mount in service["tmpfs"]:
        command.extend(["--tmpfs", mount])
    command.extend([
        "--entrypoint", "python", image, "-c",
        "import json; print(json.dumps([line.split() for line in open('/proc/mounts')]))",
    ])
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    mounts = [row for row in json.loads(result.stdout) if row[1] == target]
    assert len(mounts) == 1
    assert mounts[0][2] == "tmpfs"
    assert {"rw", "noexec", "nosuid", f"size={size}"} <= set(mounts[0][3].split(","))
