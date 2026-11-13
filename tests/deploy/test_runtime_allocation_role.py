from __future__ import annotations

import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_admin_can_replace_allocations_without_deleting_protected_history():
    postgres = os.getenv("XRAY_POSTGRES_TEST_IMAGE")
    backend = os.getenv("XRAY_BACKEND_TEST_IMAGE")
    if not postgres or not backend:
        pytest.skip(
            "PostgreSQL and backend images are required for the allocation role gate"
        )
    name = f"xray-allocation-role-{uuid4().hex}"
    start = """
set -eu
initdb -D /tmp/data --no-locale -U xray_owner -A trust >/dev/null
pg_ctl -D /tmp/data -o "-c listen_addresses=127.0.0.1 -k /tmp" -w start >/dev/null
exec tail -f /dev/null
"""
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--user",
            "70:70",
            "--tmpfs",
            "/tmp:rw,nosuid,size=256m,uid=70,gid=70",
            "--mount",
            f"type=bind,src={ROOT / 'deploy/postgres/roles.sql'},dst=/roles.sql,readonly",
            "--entrypoint",
            "/bin/sh",
            postgres,
            "-ec",
            start,
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    def run_backend(code, user="xray_owner"):
        return subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--read-only",
                "--network",
                f"container:{name}",
                "--workdir",
                "/app/backend",
                "--env",
                "DJANGO_SETTINGS_MODULE=config.settings.production",
                "--env",
                "XRAY_ENV=production",
                "--env",
                "XRAY_SECRET_KEY=fixture-only-allocation-probe",
                "--env",
                "XRAY_ALLOWED_HOSTS=admin.xray.invalid",
                "--env",
                f"XRAY_DATABASE_URL=postgresql://{user}@127.0.0.1/postgres",
                backend,
                "python",
                "-c",
                code,
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )

    try:
        ready = subprocess.run(
            [
                "docker",
                "exec",
                name,
                "sh",
                "-ec",
                "until pg_isready -h 127.0.0.1 -U xray_owner >/dev/null; do sleep 0.1; done",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert ready.returncode == 0, ready.stderr
        seeded = run_backend("""
import django
django.setup()
from django.core.management import call_command
from apps.nodes.models import NodePool
from apps.nodes.quota import set_allocations
call_command('migrate', verbosity=0, interactive=False)
pool, _ = NodePool.objects.get_or_create(singleton_key=1)
set_allocations(pool.pk, [dict(region='us-east-1',quota=1),dict(region='us-west-2',quota=0)])
""")
        assert seeded.returncode == 0, seeded.stderr
        bootstrap = subprocess.run(
            [
                "docker",
                "exec",
                "--env",
                "PGHOST=/tmp",
                "--env",
                "PGUSER=xray_owner",
                "--env",
                "PGDATABASE=postgres",
                "--env",
                "XRAY_ADMIN_DB_PASSWORD=fixture-admin",
                "--env",
                "XRAY_SUBSCRIPTION_DB_PASSWORD=fixture-subscription",
                "--env",
                "XRAY_WORKER_DB_PASSWORD=fixture-worker",
                "--env",
                "XRAY_OUTBOX_DB_PASSWORD=fixture-outbox",
                name,
                "psql",
                "-X",
                "-q",
                "-v",
                "ON_ERROR_STOP=1",
                "-f",
                "/roles.sql",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert bootstrap.returncode == 0, bootstrap.stderr
        probe = run_backend(
            """
import django
django.setup()
from django.db import connection, transaction, DatabaseError
from apps.nodes.models import NodePool,NodePoolRegionAllocation
from apps.nodes.quota import set_allocations,set_allow_create
pool = NodePool.objects.get(singleton_key=1)
set_allocations(pool.pk,[dict(region='us-east-1',quota=1)])
set_allow_create(pool.pk,True)
pool.refresh_from_db()
assert pool.allow_create and pool.quota==1
assert list(NodePoolRegionAllocation.objects.values_list('region','quota'))==[('us-east-1',1)]
set_allocations(pool.pk,[dict(region='us-east-1',quota=0)])
pool.refresh_from_db()
assert pool.quota==0
for table in ('audit_auditevent','subscriptions_securityeventrecord',
              'subscriptions_revocationtombstone','cloud_accounts_cloudcredentialversion',
              'nodes_managednode'):
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:cursor.execute('DELETE FROM '+table)
    except DatabaseError:pass
    else:raise AssertionError('admin gained forbidden history deletion')
print('admin-allocation-role-passed')
""",
            user="xray_admin_api",
        )
        assert probe.returncode == 0, probe.stderr
        assert probe.stdout.strip() == "admin-allocation-role-passed"
    finally:
        subprocess.run(
            ["docker", "stop", "--time", "1", name], capture_output=True, check=False
        )
