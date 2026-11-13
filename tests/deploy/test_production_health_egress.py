from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _production() -> dict:
    result = subprocess.run(
        [
            "docker", "compose", "--env-file",
            str(ROOT / "deploy/compose/config.example.env"),
            "--file", str(ROOT / "deploy/compose/production.yml"),
            "config", "--format", "json",
        ],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("service_name", ["admin-api", "subscription-api"])
@pytest.mark.parametrize("status", [200, 301, 503])
def test_api_healthcheck_requires_200_with_the_service_host_and_https(service_name, status):
    image = os.getenv("XRAY_BACKEND_TEST_IMAGE")
    if not image:
        pytest.skip("XRAY_BACKEND_TEST_IMAGE is required for healthcheck execution")
    service = _production()["services"][service_name]
    healthcheck = service.get("healthcheck", {}).get("test")
    if healthcheck is None:
        inspected = subprocess.run(
            ["docker", "image", "inspect", image],
            text=True, capture_output=True, check=True,
        )
        healthcheck = json.loads(inspected.stdout)[0]["Config"]["Healthcheck"]["Test"]
    command = healthcheck[1:] if healthcheck[0] == "CMD" else ["/bin/sh", "-c", healthcheck[1]]
    expected_host = {
        "admin-api": "admin.xray.invalid",
        "subscription-api": "subscription.xray.invalid",
    }[service_name]
    script = f"""
import http.server, json, subprocess, threading
requests = []
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        requests.append([self.path, self.headers.get('Host'),
                         self.headers.get('X-Forwarded-Proto')])
        valid = requests[-1] == ['/health/live', {expected_host!r}, 'https']
        self.send_response({status} if valid else 400)
        self.end_headers()
    def log_message(self, *args):
        pass
server = http.server.HTTPServer(('127.0.0.1', 8000), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
result = subprocess.run({command!r}, capture_output=True, timeout=5)
print(json.dumps(dict(exit_code=result.returncode, requests=requests)))
server.shutdown()
"""
    result = subprocess.run(
        [
            "docker", "run", "--rm", "--network", "none", "--read-only",
            "--entrypoint", "python", image, "-c", script,
        ],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    assert actual["requests"] == [["/health/live", expected_host, "https"]]
    assert (actual["exit_code"] == 0) is (status == 200)


def test_cloud_control_processes_have_egress_without_publishing_new_ports():
    document = _production()
    services = document["services"]
    networks = document["networks"]
    egress_services = {
        name for name, service in services.items()
        if any(
            not networks[network].get("internal", False)
            for network in service.get("networks", {})
        )
    }
    assert egress_services == {"admin-api", "worker", "gateway"}
    assert {name for name, service in services.items() if service.get("ports")} == {"gateway"}
    assert all(networks[name]["internal"] for name in ("control", "public-app", "data", "queue"))
