from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_worker_drain_loads_production_secrets_for_each_exec_before_stopping(tmp_path):
    image = os.getenv("XRAY_BACKEND_TEST_IMAGE")
    if not image:
        pytest.skip("XRAY_BACKEND_TEST_IMAGE is required for the worker drain gate")
    secret = tmp_path / "django-secret"
    secret.write_text("fixture-only-worker-drain-signing-value\n", encoding="utf-8")
    secret.chmod(0o444)
    db_password = tmp_path / "database-password"
    db_password.write_text("fixture-only-database-value\n", encoding="utf-8")
    db_password.chmod(0o444)
    celery = tmp_path / "celery"
    celery.write_text(
        "#!/usr/bin/env python\n"
        "import json, os, sys\n"
        "sys.path.insert(0, os.getcwd())\n"
        "import django\n"
        "django.setup()\n"
        "if sys.argv[3:] == ['control', 'cancel_consumer', 'celery']:\n"
        "    print('consumer cancelled')\n"
        "elif sys.argv[3:] == ['inspect', 'active', '--json']:\n"
        "    print(json.dumps({'fixture-worker': []}))\n"
        "else:\n"
        "    raise SystemExit(2)\n",
        encoding="utf-8",
    )
    celery.chmod(0o555)
    started = subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--workdir",
            "/app/backend",
            "--env",
            "DJANGO_SETTINGS_MODULE=config.settings.production",
            "--env",
            "XRAY_ENV=production",
            "--env",
            "XRAY_ALLOWED_HOSTS=admin.xray.invalid",
            "--env",
            "XRAY_DATABASE_HOST=127.0.0.1",
            "--env",
            "XRAY_DATABASE_NAME=xray",
            "--env",
            "XRAY_DATABASE_USER=xray_worker",
            "--env",
            "XRAY_DATABASE_PASSWORD_FILE=/run/secrets/worker_db_password",
            "--mount",
            f"type=bind,src={secret},dst=/run/secrets/django_secret_key,readonly",
            "--mount",
            f"type=bind,src={db_password},dst=/run/secrets/worker_db_password,readonly",
            "--mount",
            f"type=bind,src={celery},dst=/app/backend/.venv/bin/celery,readonly",
            image,
            "python",
            "-c",
            "import time; time.sleep(300)",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    container = started.stdout.strip()
    real_docker = subprocess.run(
        ["sh", "-c", "command -v docker"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    tools = tmp_path / "bin"
    tools.mkdir()
    docker = tools / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\n"
        "import os, subprocess, sys\n"
        "args = sys.argv[1:]\n"
        "assert args[:1] == ['compose']\n"
        "args = args[5:]\n"
        "if args == ['ps', '--status', 'running', '--services']:\n"
        "    print('worker')\n"
        "elif args[:3] == ['exec', '-T', 'worker']:\n"
        "    raise SystemExit(subprocess.run([os.environ['DRAIN_REAL_DOCKER'], 'exec', "
        "os.environ['DRAIN_CONTAINER'], *args[3:]]).returncode)\n"
        "elif args == ['stop', '-t', '60', 'worker', 'outbox-dispatcher', "
        "'security-ledger-dispatcher']:\n"
        "    raise SystemExit(subprocess.run([os.environ['DRAIN_REAL_DOCKER'], 'stop', "
        "'-t', '1', os.environ['DRAIN_CONTAINER']]).returncode)\n"
        "else:\n"
        "    raise SystemExit(2)\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    try:
        result = subprocess.run(
            [
                "sh",
                "-ec",
                ' . "$1"; wait_for_worker_drain',
                "sh",
                str(ROOT / "deploy/scripts/release-lib.sh"),
            ],
            env={
                **os.environ,
                "PATH": f"{tools}:{os.environ['PATH']}",
                "XRAY_RELEASE_CONFIG": "/fixture/config.env",
                "XRAY_RELEASE_COMPOSE": "/fixture/production.yml",
                "XRAY_WORKER_DRAIN_SECONDS": "0",
                "DRAIN_REAL_DOCKER": real_docker,
                "DRAIN_CONTAINER": container,
            },
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        stopped = subprocess.run(
            [real_docker, "inspect", container],
            text=True,
            capture_output=True,
            check=False,
        )
        assert stopped.returncode != 0 or not json.loads(stopped.stdout)[0]["State"]["Running"], (
            "worker remained running after a verified drain"
        )
    finally:
        subprocess.run(
            [real_docker, "stop", "-t", "1", container],
            text=True,
            capture_output=True,
            check=False,
        )
