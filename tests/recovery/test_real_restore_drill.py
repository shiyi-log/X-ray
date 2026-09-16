from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from django.core.management import call_command
from django.db import connection


ROOT = Path(__file__).resolve().parents[2]
TOOLS_IMAGE = os.getenv("XRAY_BACKUP_TEST_IMAGE", "")


def _docker_tools(tmp_path: Path, *command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--add-host",
            "host.docker.internal:host-gateway",
            "-v",
            f"{ROOT}:/workspace:ro",
            "-v",
            f"{tmp_path}:/work",
            "-w",
            "/workspace",
            TOOLS_IMAGE,
            *command,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.django_db(transaction=True)
def test_real_encrypted_backup_restore_stays_closed_and_imports_newer_revocation(
    tmp_path,
):
    if not TOOLS_IMAGE:
        pytest.skip("XRAY_BACKUP_TEST_IMAGE is required for the real recovery drill")

    from apps.subscriptions.models import AccessProfile, SecurityState
    from apps.subscriptions.tokens import TokenService

    database_name = connection.settings_dict["NAME"]
    assert database_name.startswith("test_xray_test")
    profile = AccessProfile.objects.create(name=f"drill-{uuid4()}")
    issued = TokenService.issue(profile.pk)
    SecurityState.objects.get_or_create(singleton_key=1, defaults={"mode": "OPEN"})

    ledger_at_backup = tmp_path / "security-at-backup.json"
    call_command("export_security_events", "--output", str(ledger_at_backup))

    keygen = _docker_tools(
        tmp_path,
        "/bin/sh",
        "-c",
        "age-keygen -o /work/identity.txt >/dev/null 2>&1 && "
        "age-keygen -y /work/identity.txt > /work/recipient.txt",
    )
    assert keygen.returncode == 0, keygen.stderr
    (tmp_path / "identity.txt").chmod(0o600)
    (tmp_path / "recipient.txt").chmod(0o600)

    service_file = tmp_path / "pg_service.conf"
    service_file.write_text(
        "[xray_backup]\n"
        "host=host.docker.internal\nport=55432\n"
        f"dbname={database_name}\nuser=xray_test\nsslmode=disable\n"
        "[restore_admin]\n"
        "host=host.docker.internal\nport=55432\n"
        "dbname=postgres\nuser=xray_test\nsslmode=disable\n",
        encoding="utf-8",
    )
    pgpass = tmp_path / "pgpass"
    pgpass.write_text(
        "host.docker.internal:55432:*:xray_test:xray_test_only_password\n",
        encoding="utf-8",
    )
    pgpass.chmod(0o600)
    backups = tmp_path / "backups"
    backups.mkdir(mode=0o700)
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    config = tmp_path / "config.env"
    config.write_text(
        "XRAY_BACKUP_DB_SERVICE=xray_backup\n"
        f"XRAY_BACKUP_DATABASE_NAME={database_name}\n"
        "XRAY_BACKUP_PG_SERVICE_FILE=/work/pg_service.conf\n"
        "XRAY_BACKUP_PGPASS_FILE=/work/pgpass\n"
        "XRAY_BACKUP_AGE_RECIPIENT_FILE=/work/recipient.txt\n"
        "XRAY_BACKUP_AGE_IDENTITY_FILE=/work/identity.txt\n"
        "XRAY_SECURITY_LEDGER_SNAPSHOT_FILE=/work/security-at-backup.json\n"
        "XRAY_RESTORE_ADMIN_SERVICE=restore_admin\n"
        "XRAY_RECOVERY_EVIDENCE_DIR=/work/evidence\n"
        "XRAY_BACKEND_IMAGE=registry.invalid/backend@sha256:"
        + "0" * 64
        + "\nXRAY_FRONTEND_IMAGE=registry.invalid/frontend@sha256:"
        + "1" * 64
        + "\nXRAY_CONTROL_KEY_VERSION=1\nXRAY_SUBSCRIPTION_KEY_VERSION=1\n",
        encoding="utf-8",
    )

    backup = _docker_tools(
        tmp_path,
        "/workspace/deploy/backup/backup.sh",
        "--destination",
        "/work/backups",
        "--config",
        "/work/config.env",
    )
    assert backup.returncode == 0, backup.stderr
    container_backup_dir = backup.stdout.strip().splitlines()[-1]
    backup_dir = tmp_path / "backups" / Path(container_backup_dir).name
    assert (backup_dir / "manifest.json").is_file()

    TokenService.disable(issued.subscription_id)
    ledger_dir = tmp_path / "external-ledger"
    call_command("dispatch_security_events", "--directory", str(ledger_dir))
    current_ledger = tmp_path / "security-current.json"
    call_command("export_security_events", "--output", str(current_ledger))
    current_document = json.loads(current_ledger.read_text(encoding="utf-8"))
    assert current_document["expected_sequence"] == 1

    target = f"xray_restore_{uuid4().hex}"
    try:
        restore = _docker_tools(
            tmp_path,
            "/workspace/deploy/backup/restore.sh",
            "--backup",
            f"/work/backups/{backup_dir.name}",
            "--target",
            target,
            "--config",
            "/work/config.env",
        )
        assert restore.returncode == 0, restore.stderr
        receipt = tmp_path / "evidence" / Path(restore.stdout.strip().splitlines()[-1]).name
        receipt_document = json.loads(receipt.read_text(encoding="utf-8"))
        assert receipt_document["security_mode"] == "MAINTENANCE"
        assert receipt_document["network_mode"] == "isolated"

        recovery_env = os.environ.copy()
        recovery_env.update(
            {
                "DJANGO_SETTINGS_MODULE": "config.settings.recovery",
                "XRAY_ENV": "recovery",
                "XRAY_DATABASE_URL": (
                    "postgresql://xray_test:xray_test_only_password@127.0.0.1:55432/"
                    + target
                ),
                "XRAY_ALLOWED_HOSTS": "localhost",
                "XRAY_SECRET_KEY": "recovery-test-only-secret-key",
                "XRAY_RECOVERY_CONFIRM": "MAINTENANCE",
            }
        )
        reconcile = subprocess.run(
            [
                str(ROOT / "backend/.venv/bin/python"),
                str(ROOT / "backend/manage.py"),
                "reconcile_after_restore",
                "--confirm",
                "LOCK RESTORED SYSTEM",
                "--events",
                str(current_ledger),
                "--expected-sequence",
                "1",
            ],
            cwd=ROOT,
            env=recovery_env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert reconcile.returncode == 0, reconcile.stderr

        with psycopg.connect(
            host="127.0.0.1",
            port=55432,
            dbname=target,
            user="xray_test",
            password="xray_test_only_password",
        ) as restored:
            mode = restored.execute(
                "SELECT mode FROM subscriptions_securitystate WHERE singleton_key = 1"
            ).fetchone()[0]
            tombstones = restored.execute(
                "SELECT count(*) FROM subscriptions_revocationtombstone"
            ).fetchone()[0]
        assert mode == "MAINTENANCE"
        assert tombstones == 1

        token_check_env = recovery_env | {"XRAY_DRILL_TOKEN": issued.raw_token}
        token_check = subprocess.run(
            [
                str(ROOT / "backend/.venv/bin/python"),
                "-c",
                "import os,django; django.setup(); "
                "from apps.subscriptions.tokens import TokenGone,TokenService; "
                "token=os.environ['XRAY_DRILL_TOKEN']; "
                "\ntry: TokenService.resolve(token)\n"
                "except TokenGone: raise SystemExit(0)\n"
                "raise SystemExit(1)",
            ],
            cwd=ROOT / "backend",
            env=token_check_env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert token_check.returncode == 0, token_check.stderr
    finally:
        if target.startswith("xray_restore_"):
            with psycopg.connect(
                host="127.0.0.1",
                port=55432,
                dbname="postgres",
                user="xray_test",
                password="xray_test_only_password",
                autocommit=True,
            ) as admin:
                admin.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (target,),
                )
                admin.execute(f'DROP DATABASE IF EXISTS "{target}"')
