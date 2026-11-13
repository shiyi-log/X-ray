from __future__ import annotations

import importlib.util
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "xray_upgrade_runner", ROOT / "deploy/upgrade/runner.py"
)


@pytest.fixture
def runner_module():
    assert SPEC is not None and SPEC.loader is not None
    module = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(module)
    return module


def write_json(path, value, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    path.chmod(mode)


@pytest.fixture
def queue(tmp_path, runner_module, monkeypatch):
    root = tmp_path / "upgrade"
    root.mkdir()
    for folder in ("requests", "results", "releases"):
        (root / folder).mkdir()
    release = root / "releases/0.14.9"
    source = release / "source"
    (source / "deploy/scripts").mkdir(parents=True)
    (source / "deploy/compose").mkdir()
    (source / "deploy/backup").mkdir()
    (source / "installer").mkdir()
    (source / "VERSION").write_text("0.14.9\n")
    (source / "deploy/compose/production.yml").write_text("name: xray-production\n")
    script = source / "deploy/scripts/release.sh"
    script.write_text(
        "#!/usr/bin/env python3\nimport os,pathlib\n"
        'pathlib.Path(os.environ["XRAY_TEST_RELEASE_MARKER"]).write_text("executed")\n'
        'raise SystemExit(int(os.getenv("XRAY_TEST_RELEASE_EXIT","0")))\n'
    )
    script.chmod(0o755)
    write_json(
        release / "manifest.json",
        {
            "schema_version": 1,
            "version": "0.14.9",
            "backend_image": "127.0.0.1:15000/xray/backend@sha256:" + "a" * 64,
            "frontend_image": "127.0.0.1:15000/xray/frontend@sha256:" + "b" * 64,
        },
    )
    write_json(
        root / "catalog.json",
        {"schema_version": 1, "releases": [{"version": "0.14.9"}]},
    )
    config = tmp_path / "config.env"
    config.write_text(
        "XRAY_BACKEND_IMAGE=previous-backend@sha256:"
        + "c" * 64
        + "\nXRAY_FRONTEND_IMAGE=previous-frontend@sha256:"
        + "d" * 64
        + "\nXRAY_SECURITY_LEDGER_HOST_DIR="
        + str(tmp_path / "ledger")
        + "\n"
    )
    config.chmod(0o600)
    current = tmp_path / "VERSION"
    current.write_text("0.14.8")
    marker = tmp_path / "executed"
    monkeypatch.setenv("XRAY_TEST_RELEASE_MARKER", str(marker))
    runner = runner_module.Runner(root, config, current, trusted_uid=os.getuid())

    def export_snapshot(source, output):
        write_json(
            output, {"schema_version": 1, "expected_sequence": 0, "events": []}, 0o600
        )

    monkeypatch.setattr(runner, "_export_snapshot", export_snapshot)
    return runner, root, release, config, marker


def submit(root, *, age=0, version="0.14.9"):
    job = str(uuid4())
    write_json(
        root / "requests" / (job + ".json"),
        {
            "schema_version": 1,
            "id": job,
            "version": version,
            "created_at": (datetime.now(UTC) - timedelta(seconds=age)).isoformat(),
            "actor_id": "1",
        },
        0o600,
    )
    return job


def test_runner_executes_only_prepared_release_and_persists_safe_result(queue):
    runner, root, release, config, marker = queue
    job = submit(root)
    assert runner.tick() == 1
    result = json.loads((root / "results" / (job + ".json")).read_text())
    assert (result["status"], result["phase"], result["error_code"]) == (
        "SUCCEEDED",
        "COMPLETE",
        "",
    )
    assert marker.read_text() == "executed"
    assert "backend@sha256:" + "a" * 64 in config.read_text()
    assert (root / "history" / (job + ".env")).stat().st_mode & 0o777 == 0o600
    assert runner.tick() == 0


@pytest.mark.parametrize(
    "version,age,code",
    [
        ("../../outside", 0, "REQUEST_INVALID"),
        ("0.14.9", 5400, "REQUEST_EXPIRED"),
        ("0.14.9", -61, "REQUEST_INVALID"),
        ("0.14.7", 0, "RELEASE_UNAVAILABLE"),
    ],
)
def test_runner_rejects_invalid_requests_before_execution(queue, version, age, code):
    runner, root, _release, _config, marker = queue
    job = submit(root, version=version, age=age)
    runner.tick()
    result = json.loads((root / "results" / (job + ".json")).read_text())
    assert result["status"] == "FAILED"
    assert result["error_code"] == code
    if version == "0.14.9":
        assert result["version"] == version
    assert not marker.exists()


@pytest.mark.parametrize("actor", ["0", "-1", "01", str(uuid4()), "", 1])
def test_runner_rejects_invalid_administrator_id(queue, actor):
    runner, root, _release, _config, marker = queue
    job = submit(root)
    request = root / "requests" / (job + ".json")
    record = json.loads(request.read_text())
    record["actor_id"] = actor
    write_json(request, record)
    runner.tick()
    assert (
        json.loads((root / "results" / request.name).read_text())["status"] == "FAILED"
    )
    assert not marker.exists()


@pytest.mark.parametrize(
    "unsafe", ["source_symlink", "manifest_writable", "source_writable"]
)
def test_runner_refuses_api_writable_or_symlink_release_artifacts(queue, unsafe):
    runner, root, release, _config, marker = queue
    if unsafe == "source_symlink":
        source = release / "source"
        moved = release / "moved"
        source.rename(moved)
        source.symlink_to(moved, target_is_directory=True)
    elif unsafe == "manifest_writable":
        (release / "manifest.json").chmod(0o666)
    else:
        (release / "source/deploy/scripts/release.sh").chmod(0o777)
    job = submit(root)
    runner.tick()
    result = json.loads((root / "results" / (job + ".json")).read_text())
    assert result["status"] == "FAILED"
    assert result["error_code"] == "RELEASE_UNTRUSTED"
    assert not marker.exists()


def test_runner_restores_configuration_on_release_failure_without_restoring_database(
    queue, monkeypatch
):
    runner, root, _release, config, marker = queue
    original = config.read_bytes()
    monkeypatch.setenv("XRAY_TEST_RELEASE_EXIT", "1")
    job = submit(root)
    runner.tick()
    result = json.loads((root / "results" / (job + ".json")).read_text())
    assert result["status"] == "FAILED"
    assert result["phase"] == "ROLLBACK_REQUIRED"
    assert result["error_code"] == "RELEASE_FAILED"
    assert config.read_bytes() == original
    assert marker.exists()
    assert "executed" not in json.dumps(result)


def test_runner_lock_prevents_a_second_executor(queue):
    import fcntl

    runner, root, _release, _config, marker = queue
    submit(root)
    with (root / ".runner.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert runner.tick() == 0
    assert not marker.exists()


def test_runner_waits_for_atomic_api_publish_before_reading_request(queue):
    import fcntl
    import threading

    runner, root, _release, _config, marker = queue
    job = submit(root)
    request = root / "requests" / (job + ".json")
    incoming = root / "requests/.incoming-test"
    os.link(request, incoming)
    finished = threading.Event()

    def execute():
        runner.tick()
        finished.set()

    with (root / "requests/queue.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        thread = threading.Thread(target=execute)
        thread.start()
        try:
            assert not finished.wait(timeout=0.1)
        finally:
            incoming.unlink()
            fcntl.flock(lock, fcntl.LOCK_UN)
            thread.join(timeout=3)
    assert finished.is_set()
    assert marker.read_text() == "executed"
    assert (
        json.loads((root / "results" / request.name).read_text())["status"]
        == "SUCCEEDED"
    )


def test_terminal_history_does_not_starve_pending_requests(queue):
    runner, root, _release, _config, marker = queue
    pending = submit(root)
    pending_record = (root / "requests" / (pending + ".json")).read_bytes()
    (root / "requests" / (pending + ".json")).unlink()
    pending = "ffffffff-ffff-4fff-bfff-ffffffffffff"
    record = json.loads(pending_record)
    record["id"] = pending
    write_json(root / "requests" / (pending + ".json"), record)
    for index in range(101):
        historical = f"00000000-0000-4000-8000-{index:012x}"
        record["id"] = historical
        write_json(root / "requests" / (historical + ".json"), record)
        write_json(
            root / "results" / (historical + ".json"),
            {"status": "SUCCEEDED"},
        )
    assert runner.tick() == 1
    assert marker.exists()
    assert (
        json.loads((root / "results" / (pending + ".json")).read_text())["status"]
        == "SUCCEEDED"
    )


def test_security_export_uses_a_one_off_container_and_keeps_only_private_snapshot(
    queue, runner_module, monkeypatch
):
    runner, root, release, config, _marker = queue
    history = root / "history"
    history.mkdir(mode=0o700)
    output = history / "security.json"
    commands = []
    monkeypatch.setattr(runner_module.os, "chown", lambda *_args: None)

    def execute(command, *, timeout):
        commands.append((command, timeout))
        mount = command[command.index("-v") + 1]
        source, target = mount.rsplit(":", 1)
        assert target == "/upgrade-export"
        write_json(
            Path(source) / "security.json",
            {"schema_version": 1, "expected_sequence": 7, "events": []},
            0o600,
        )

    monkeypatch.setattr(runner, "_execute", execute)
    runner_module.Runner._export_snapshot(runner, release / "source", output)
    command, timeout = commands[0]
    assert command[:4] == ["docker", "compose", "--env-file", str(config)]
    assert command[-6:] == [
        "admin-api",
        "python",
        "/app/backend/manage.py",
        "export_security_events",
        "--output",
        "/upgrade-export/security.json",
    ]
    assert timeout == 120
    assert json.loads(output.read_text())["expected_sequence"] == 7
    assert output.stat().st_mode & 0o777 == 0o600
    assert list(history.iterdir()) == [output]


def test_export_failure_never_changes_config_or_runs_release_and_hides_exception(
    queue, monkeypatch
):
    runner, root, _release, config, marker = queue
    original = config.read_bytes()

    def failed_export(*_args):
        raise RuntimeError("secret-bearing-error-must-not-be-persisted")

    monkeypatch.setattr(runner, "_export_snapshot", failed_export)
    job = submit(root)
    runner.tick()
    serialized = (root / "results" / (job + ".json")).read_text()
    assert json.loads(serialized)["status"] == "FAILED"
    assert "secret-bearing-error" not in serialized
    assert config.read_bytes() == original
    assert not marker.exists()


def test_runner_rejects_a_downgrade_even_if_catalog_allows_it(queue):
    runner, root, _release, _config, marker = queue
    runner.current_version.write_text("0.15.0")
    job = submit(root)
    runner.tick()
    result = json.loads((root / "results" / (job + ".json")).read_text())
    assert result["error_code"] == "DOWNGRADE_FORBIDDEN"
    assert not marker.exists()


def test_interrupted_release_is_marked_for_operator_recovery_without_reexecution(queue):
    runner, root, _release, _config, marker = queue
    job = submit(root)
    write_json(
        root / "results" / (job + ".json"),
        {
            "id": job,
            "version": "0.14.9",
            "status": "RUNNING",
            "phase": "RELEASING",
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    assert runner.tick() == 0
    result = json.loads((root / "results" / (job + ".json")).read_text())
    assert (result["status"], result["phase"], result["error_code"]) == (
        "FAILED",
        "ROLLBACK_REQUIRED",
        "UPGRADE_INTERRUPTED",
    )
    assert not marker.exists()


def test_upgrade_mount_is_admin_only_and_does_not_expose_docker_socket():
    import subprocess

    rendered = subprocess.run(
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
    services = json.loads(rendered.stdout)["services"]
    admin = services["admin-api"]
    assert admin["environment"]["XRAY_UPGRADE_ROOT"] == "/var/lib/xray/upgrade"
    assert any(
        volume.get("source") == "/var/lib/xray/upgrade"
        and volume["target"] == "/var/lib/xray/upgrade"
        for volume in admin["volumes"]
    )
    for name, service in services.items():
        for volume in service.get("volumes", []):
            assert "docker.sock" not in volume.get("source", "")
            assert (
                name == "admin-api" or volume.get("target") != "/var/lib/xray/upgrade"
            )
