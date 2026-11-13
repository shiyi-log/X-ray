from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_subscription_gunicorn_access_log_omits_the_bearer_path():
    image = os.getenv("XRAY_BACKEND_TEST_IMAGE")
    if not image:
        pytest.skip("backend image required for real Gunicorn logging gate")
    config = subprocess.run(
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
        capture_output=True,
        text=True,
        check=True,
    )
    command = json.loads(config.stdout)["services"]["subscription-api"]["command"]
    command[command.index("--chdir") + 1] = "/tmp"
    command[-1] = "probe:application"
    script = f"""
import pathlib, subprocess, time, urllib.request
pathlib.Path('/tmp/probe.py').write_text("def application(environ,start_response):\\n start_response('200 OK', [('Content-Type','text/plain')]); return [b'ok']\\n")
process = subprocess.Popen({command!r}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    for _ in range(100):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8000/s/'+'A'*43, timeout=.2) as response:
                assert response.status == 200
            break
        except OSError:
            time.sleep(.05)
    else:
        raise RuntimeError('Gunicorn not ready')
finally:
    process.terminate()
output, _ = process.communicate(timeout=10)
print(output)
"""
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--read-only",
            "--network",
            "none",
            "--tmpfs",
            "/tmp:rw,nosuid,size=32m",
            "--entrypoint",
            "python",
            image,
            "-c",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "A" * 43 not in result.stdout
    assert "/s/" not in result.stdout
    assert "GET 200" in result.stdout
