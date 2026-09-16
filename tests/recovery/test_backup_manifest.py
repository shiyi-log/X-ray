from __future__ import annotations

import json
import subprocess
from pathlib import Path

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


def test_backup_tools_are_version_and_digest_pinned():
    dockerfile = (ROOT / "deploy/docker/backup-tools.Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "ARG AGE_VERSION=1.2.1" in dockerfile
    assert "releases/download/v${AGE_VERSION}" in dockerfile
    assert "7df45a6cc87d4da11cc03a539a7470c15b1041ab2b396af088fe9990f7c79d50" in dockerfile
    assert "57fd79a7ece5fe501f351b9dd51a82fbee1ea8db65a8839db17f5c080245e99f" in dockerfile
    assert "postgres@sha256:" in dockerfile
