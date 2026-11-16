from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]


def test_backup_manifest_schema_requires_recovery_and_security_metadata():
    schema = json.loads(
        (ROOT / "deploy/backup/manifest.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    required = set(schema["required"])
    assert {
        "schema_version",
        "app_version",
        "created_at",
        "database_name",
        "encrypted_dump",
        "encrypted_sha256",
        "plaintext_sha256",
        "security_ledger_sequence",
        "security_ledger_sha256",
        "backend_image",
        "frontend_image",
        "installer_manifest_sha256",
        "control_key_version",
        "subscription_key_version",
    }.issubset(required)


def test_restore_script_rejects_running_or_non_restore_database_name(tmp_path):
    config = tmp_path / "config.env"
    config.write_text("XRAY_BACKUP_DB_SERVICE=source\n", encoding="utf-8")
    result = subprocess.run(
        [
            str(ROOT / "deploy/backup/restore.sh"),
            "--backup",
            str(tmp_path / "missing"),
            "--target",
            "xray",
            "--config",
            str(config),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "xray_restore_" in result.stderr


def _run_restore_target_check(tmp_path: Path, result_mode: str):
    """Run the real shell flow with external restore effects stopped at createdb."""
    backup_scripts = tmp_path / "deploy/backup"
    release_scripts = tmp_path / "deploy/scripts"
    backup_scripts.mkdir(parents=True)
    release_scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "deploy/backup/restore.sh", backup_scripts / "restore.sh")
    shutil.copy2(ROOT / "deploy/scripts/release-lib.sh", release_scripts / "release-lib.sh")
    verify = backup_scripts / "verify.sh"
    verify.write_text(
        "#!/bin/sh\nprintf 'verify\\n' >>\"$RESTORE_TEST_CALLS\"\n", encoding="utf-8"
    )
    verify.chmod(0o755)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    psql = fake_bin / "psql"
    psql.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "from pathlib import Path\n"
        "with Path(os.environ['RESTORE_TEST_CALLS']).open('a') as calls:\n"
        "    calls.write('psql\\n')\n"
        "args = sys.argv[1:]\n"
        "# psql -c sends SQL directly: it does not interpolate psql variables.\n"
        "command = next((arg.split('=', 1)[1] for arg in args if arg.startswith('--command=')), '')\n"
        "if command and \":'target'\" in command:\n"
        "    raise SystemExit(1)\n"
        "sql = command or sys.stdin.read()\n"
        "if not sql.strip():\n"
        "    raise SystemExit(2)\n"
        "mode = os.environ['RESTORE_TEST_RESULT']\n"
        "if mode == 'failure':\n"
        "    raise SystemExit(2)\n"
        "if mode == 'failure-with-output':\n"
        "    print('f')\n"
        "    raise SystemExit(2 if '--set=ON_ERROR_STOP=1' in args else 0)\n"
        "if mode == 'exists':\n"
        "    print('t' if 'EXISTS' in sql.upper() else '1')\n"
        "elif mode == 'missing':\n"
        "    if 'EXISTS' in sql.upper():\n"
        "        print('f')\n"
        "elif mode == 'unexpected':\n"
        "    print('unexpected')\n",
        encoding="utf-8",
    )
    psql.chmod(0o755)
    createdb = fake_bin / "createdb"
    createdb.write_text(
        "#!/bin/sh\nprintf 'createdb\\n' >>\"$RESTORE_TEST_CALLS\"\nexit 78\n",
        encoding="utf-8",
    )
    createdb.chmod(0o755)

    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    pg_service = tmp_path / "pg_service.conf"
    pg_service.touch()
    pgpass = tmp_path / "pgpass"
    pgpass.touch(mode=0o600)
    identity = tmp_path / "age-identity"
    identity.touch(mode=0o600)
    config = tmp_path / "config.env"
    config.write_text(
        f"XRAY_RESTORE_ADMIN_SERVICE=restore_admin\n"
        f"XRAY_BACKUP_PG_SERVICE_FILE={pg_service}\n"
        f"XRAY_BACKUP_PGPASS_FILE={pgpass}\n"
        f"XRAY_RECOVERY_EVIDENCE_DIR={tmp_path / 'evidence'}\n"
        f"XRAY_BACKUP_AGE_IDENTITY_FILE={identity}\n",
        encoding="utf-8",
    )
    calls = tmp_path / "calls"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "RESTORE_TEST_CALLS": str(calls),
        "RESTORE_TEST_RESULT": result_mode,
    }
    result = subprocess.run(
        [
            str(backup_scripts / "restore.sh"),
            "--backup", str(backup_dir),
            "--target", "xray_restore_target_check",
            "--config", str(config),
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    return result, calls.read_text(encoding="utf-8").splitlines()


def test_restore_rejects_existing_database_before_verification_or_creation(tmp_path):
    result, calls = _run_restore_target_check(tmp_path, "exists")
    assert result.returncode != 0
    assert "restore target already exists" in result.stderr
    assert calls == ["psql"]


@pytest.mark.parametrize("result_mode", ["failure", "failure-with-output", "empty", "unexpected"])
def test_restore_target_query_fails_closed_before_verification_or_creation(tmp_path, result_mode):
    result, calls = _run_restore_target_check(tmp_path, result_mode)
    assert result.returncode not in (0, 78)
    assert calls == ["psql"]


def test_restore_verifies_backup_then_creates_only_a_confirmed_missing_database(tmp_path):
    result, calls = _run_restore_target_check(tmp_path, "missing")
    assert result.returncode == 78
    assert calls == ["psql", "verify", "createdb"]


def test_backup_tools_are_version_and_digest_pinned():
    dockerfile = (ROOT / "deploy/docker/backup-tools.Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "ARG AGE_VERSION=1.2.1" in dockerfile
    assert "releases/download/v${AGE_VERSION}" in dockerfile
    assert "7df45a6cc87d4da11cc03a539a7470c15b1041ab2b396af088fe9990f7c79d50" in dockerfile
    assert "57fd79a7ece5fe501f351b9dd51a82fbee1ea8db65a8839db17f5c080245e99f" in dockerfile
    assert "postgres@sha256:" in dockerfile
    assert 'target_arch="${TARGETARCH:-$(uname -m)}"' in dockerfile
    assert "amd64|x86_64)" in dockerfile
    assert "arm64|aarch64)" in dockerfile
    assert "${target_arch}" in dockerfile
