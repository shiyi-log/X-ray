from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "service_name", ["worker", "beat", "outbox-dispatcher", "security-ledger-dispatcher"]
)
def test_non_http_daemons_do_not_inherit_the_api_http_probe(service_name):
    image = os.getenv("XRAY_BACKEND_TEST_IMAGE")
    if not image:
        pytest.skip("XRAY_BACKEND_TEST_IMAGE is required for the daemon health gate")
    configured = subprocess.run(
        [
            "docker", "compose", "--env-file",
            str(ROOT / "deploy/compose/config.example.env"),
            "--file", str(ROOT / "deploy/compose/production.yml"),
            "config", "--format", "json",
        ],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    service = json.loads(configured.stdout)["services"][service_name]
    args = ["docker", "run", "--rm", "--detach", "--network", "none", "--read-only"]
    if service.get("healthcheck", {}).get("disable"):
        args.append("--no-healthcheck")
    args.extend([
        "--entrypoint", "python", image, "-c", "import time; time.sleep(30)",
    ])
    started = subprocess.run(args, text=True, capture_output=True, check=True)
    container = started.stdout.strip()
    try:
        inspected = subprocess.run(
            ["docker", "inspect", container], text=True, capture_output=True, check=True,
        )
        metadata = json.loads(inspected.stdout)[0]
        assert metadata["State"]["Running"] is True
        assert metadata["Config"]["Healthcheck"]["Test"] == ["NONE"]
        assert "Health" not in metadata["State"]
    finally:
        subprocess.run(
            ["docker", "stop", "--time", "1", container],
            text=True, capture_output=True, check=True,
        )
