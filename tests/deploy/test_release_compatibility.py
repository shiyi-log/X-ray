from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = ROOT / "deploy/scripts/preflight.sh"
EXAMPLE = ROOT / "deploy/compose/config.example.env"


def _preflight_fixture(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    secret_keys = {
        "XRAY_DJANGO_SECRET_KEY_FILE",
        "XRAY_CONTROL_MASTER_KEY_FILE",
        "XRAY_SUBSCRIPTION_MASTER_KEY_FILE",
        "XRAY_OWNER_DB_PASSWORD_FILE",
        "XRAY_ADMIN_DB_PASSWORD_FILE",
        "XRAY_SUBSCRIPTION_DB_PASSWORD_FILE",
        "XRAY_WORKER_DB_PASSWORD_FILE",
        "XRAY_OUTBOX_DB_PASSWORD_FILE",
        "XRAY_CLOUD_CREDENTIALS_FILE",
        "XRAY_ADMIN_TLS_KEY_FILE",
        "XRAY_SUBSCRIPTION_TLS_KEY_FILE",
    }
    public_keys = {"XRAY_ADMIN_TLS_CERT_FILE", "XRAY_SUBSCRIPTION_TLS_CERT_FILE"}
    files: dict[str, Path] = {}
    output: list[str] = []
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            output.append(line)
            continue
        key, value = line.split("=", 1)
        if key in secret_keys | public_keys:
            value = str(tmp_path / key.lower())
            target = Path(value)
            target.write_text("fixture-only\n", encoding="utf-8")
            target.chmod(0o600 if key in secret_keys else 0o644)
            files[key] = target
        elif key == "XRAY_RELEASE_BACKUP_DESTINATION":
            value = str(tmp_path / "offsite")
        output.append(f"{key}={value}")
    config = tmp_path / "config.env"
    config.write_text("\n".join(output) + "\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    docker.chmod(0o755)
    return config, files


def _run_preflight(config: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path / 'bin'}:{env['PATH']}"
    return subprocess.run(
        [
            str(PREFLIGHT),
            "--config",
            str(config),
            "--compose",
            str(ROOT / "deploy/compose/production.yml"),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_preflight_accepts_complete_non_secret_config_and_restricted_secret_files(
    tmp_path,
):
    config, _files = _preflight_fixture(tmp_path)
    result = _run_preflight(config, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "preflight passed" in result.stdout
    assert "fixture-only" not in result.stdout + result.stderr


def test_preflight_rejects_mutable_image_reference(tmp_path):
    config, _files = _preflight_fixture(tmp_path)
    content = config.read_text(encoding="utf-8").replace(
        "registry.invalid/xray/backend@sha256:"
        + "0" * 64,
        "registry.invalid/xray/backend:latest",
    )
    config.write_text(content, encoding="utf-8")
    result = _run_preflight(config, tmp_path)
    assert result.returncode != 0
    assert "immutable sha256" in result.stderr


def test_preflight_rejects_world_readable_secret(tmp_path):
    config, files = _preflight_fixture(tmp_path)
    files["XRAY_DJANGO_SECRET_KEY_FILE"].chmod(
        stat.S_IRUSR | stat.S_IWUSR | stat.S_IROTH
    )
    result = _run_preflight(config, tmp_path)
    assert result.returncode != 0
    assert "must not be readable by other users" in result.stderr


def test_rollback_is_application_only_and_release_checks_migration_compatibility():
    rollback = (ROOT / "deploy/scripts/rollback.sh").read_text(encoding="utf-8")
    release = (ROOT / "deploy/scripts/release.sh").read_text(encoding="utf-8")
    assert "pg_restore" not in rollback
    assert "migrate" not in rollback
    assert "REVOCATION" in rollback
    assert "migrate --plan" in release
    assert "migrate --check" in release
    assert "wait_for_worker_drain" in release
