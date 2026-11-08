from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SANITIZER = ROOT / "scripts/sanitize-playwright-trace.py"


def run_sanitizer(target: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SANITIZER), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_sanitized_trace_keeps_evidence_without_authenticated_context(tmp_path):
    target = tmp_path / "test-trace.zip"
    options = {
        "viewport": {"width": 1280, "height": 720},
        "storageState": {
            "cookies": [{"name": "xray_test_session", "value": "test-only-cookie"}],
            "origins": [
                {"localStorage": [{"name": "token", "value": "test-only-value"}]}
            ],
        },
        "httpCredentials": {"username": "test-user", "password": "test-only-password"},
        "extraHTTPHeaders": {"Authorization": "test-only-header"},
        "proxy": {"server": "http://127.0.0.1", "password": "test-only-proxy"},
    }
    context = {"type": "context-options", "options": options}
    event = {"type": "before", "apiName": "page.reload", "callId": "call@1"}
    with zipfile.ZipFile(target, "w") as bundle:
        bundle.writestr(
            "trace.trace", json.dumps(context) + "\n" + json.dumps(event) + "\n"
        )
        bundle.writestr("trace.network", "test-only-network-data")
        bundle.writestr("nested/1-trace.network", "test-only-network-data")
        bundle.writestr("resources/screenshot.jpeg", b"synthetic-image-evidence")
        bundle.writestr("trace.stacks", b"synthetic-stack-evidence")

    result = run_sanitizer(target)

    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(target) as bundle:
        assert set(bundle.namelist()) == {
            "trace.trace",
            "resources/screenshot.jpeg",
            "trace.stacks",
        }
        records = [json.loads(line) for line in bundle.read("trace.trace").splitlines()]
        assert records == [
            {
                "type": "context-options",
                "options": {"viewport": {"width": 1280, "height": 720}},
            },
            {"type": "before", "apiName": "page.reload", "callId": "call@1"},
        ]
        assert bundle.read("resources/screenshot.jpeg") == b"synthetic-image-evidence"
        assert bundle.read("trace.stacks") == b"synthetic-stack-evidence"
        assert all(b"test-only-" not in bundle.read(name) for name in bundle.namelist())

    assert run_sanitizer(target).returncode == 0
    assert sorted(path.name for path in tmp_path.iterdir()) == ["test-trace.zip"]


@pytest.mark.parametrize("malformed_trace", [False, True])
def test_invalid_trace_cannot_be_uploaded_after_sanitizer_failure(
    tmp_path, malformed_trace
):
    target = tmp_path / "unsafe-trace.zip"
    if malformed_trace:
        with zipfile.ZipFile(target, "w") as bundle:
            bundle.writestr("trace.trace", "invalid-json test-only-private-marker")
    else:
        target.write_bytes(b"invalid-zip test-only-private-marker")

    result = run_sanitizer(target)

    assert result.returncode == 2
    assert not target.exists()
    assert "test-only-private-marker" not in result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == []
