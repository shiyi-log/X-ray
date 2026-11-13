from __future__ import annotations

import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_worker_role_runs_schedulers_usage_and_publication_without_control_mutation():
    postgres = os.getenv("XRAY_POSTGRES_TEST_IMAGE")
    backend = os.getenv("XRAY_BACKEND_TEST_IMAGE")
    if not postgres or not backend:
        pytest.skip("PostgreSQL and backend images are required for the runtime role gate")
    name = f"xray-runtime-role-{uuid4().hex}"
    start = r"""
set -eu
initdb -D /tmp/data --no-locale -U xray_owner -A trust >/dev/null
pg_ctl -D /tmp/data -o "-c listen_addresses=127.0.0.1 -k /tmp" -w start >/dev/null
exec tail -f /dev/null
"""
    subprocess.run(
        [
            "docker", "run", "--detach", "--rm", "--name", name,
            "--network", "none", "--read-only", "--user", "70:70",
            "--tmpfs", "/tmp:rw,nosuid,size=256m,uid=70,gid=70",
            "--mount",
            f"type=bind,src={ROOT / 'deploy/postgres/roles.sql'},dst=/roles.sql,readonly",
            "--entrypoint", "/bin/sh", postgres, "-ec", start,
        ],
        capture_output=True, text=True, check=True,
    )

    def run_backend(code: str, *, user: str = "xray_owner"):
        return subprocess.run(
            [
                "docker", "run", "--rm", "--read-only",
                "--network", f"container:{name}", "--workdir", "/app/backend",
                "--env", "DJANGO_SETTINGS_MODULE=config.settings.production",
                "--env", "XRAY_ENV=production",
                "--env", "XRAY_SECRET_KEY=fixture-only-role-probe",
                "--env", "XRAY_SUBSCRIPTION_MASTER_KEY=" + "f" * 32,
                "--env", "XRAY_ALLOWED_HOSTS=admin.xray.invalid",
                "--env", f"XRAY_DATABASE_URL=postgresql://{user}@127.0.0.1/postgres",
                backend, "python", "-c", code,
            ],
            capture_output=True, text=True, timeout=90, check=False,
        )

    try:
        ready = subprocess.run(
            ["docker", "exec", name, "sh", "-ec",
             "until pg_isready -h 127.0.0.1 -U xray_owner >/dev/null; do sleep 0.1; done"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        assert ready.returncode == 0, ready.stderr
        seeded = run_backend("""
import django
django.setup()
from django.core.management import call_command
from django.utils import timezone
from uuid import uuid4
from apps.identity.models import SuperAdmin, NodeAutomationSetting, NodeStatusSyncSetting
from apps.cloud_accounts.models import CloudAccount, CloudCredentialVersion
from apps.nodes.models import (NodePool, NodePoolRegionAllocation, ManagedNode,
                               NodeProtocol, NodeConfigRevision)
from apps.subscriptions.models import (AccessProfile, NodeCredential, SubscriptionPool,
                                      Subscription, SubscriptionToken)
from common.crypto import configured_subscription_store
import json
call_command('migrate', verbosity=0, interactive=False)
SuperAdmin.objects.create_superuser('role-probe', 'fixture-only-password')
account = CloudAccount.objects.create(name='probe', provider='aws_lightsail',
                                     external_account_id='fixture-account')
version = CloudCredentialVersion.objects.create(account=account, version=1,
    encrypted_credentials={}, identity_verified_at=timezone.now())
pool, _ = NodePool.objects.get_or_create(singleton_key=1, defaults={'name': 'fixture-pool'})
pool.quota = 2
pool.region = 'us-east-1'
pool.save()
NodePoolRegionAllocation.objects.filter(pool=pool).delete()
NodePoolRegionAllocation.objects.create(pool=pool, region='us-east-1', quota=2)
NodeAutomationSetting.objects.create(pool_sync_enabled=True,
    pool_sync_creation_templates=[dict(region='us-east-1', cloud_account_id=str(account.pk),
                                     plan_id='small_3_0', image_id='ubuntu_24_04')])
NodeStatusSyncSetting.objects.create(enabled=True)
node = ManagedNode.objects.create(pool=pool, cloud_account=account,
    cloud_credential_version=version, region='us-east-1', plan_id='small_3_0',
    image_id='ubuntu_24_04', deterministic_name='fixture-node', operation_key=uuid4(),
    external_id='fixture-instance', provisioning_state='READY', raw_cloud_state='running',
    health_state='HEALTHY', addresses=[dict(family=4, value='192.0.2.10')])
profile = AccessProfile.objects.create(name='fixture-profile')
protocol = NodeProtocol.objects.create(node=node, protocol='vmess', port=10000)
credential = NodeCredential(id=uuid4(), node=node, profile=profile, protocol=protocol,
    version=1, desired_generation=0)
credential.encrypted_material = configured_subscription_store().encrypt(
    json.dumps(dict(id=str(uuid4()))).encode(), purpose='subscription.credential',
    aad=f'credential:{credential.pk}:1:material'.encode())
credential.save()
NodeConfigRevision.objects.create(node=node, generation=0, config_hash='fixture',
    xray_version='fixture', installer_version='fixture', bundle_hash='fixture', usable=True,
    probe_result=dict(generation=0, app_health_passed=True, accepted=True,
                      positive_control=True, fresh_connection=True))
subscription_pool = SubscriptionPool.objects.get(singleton_key=1)
subscription = Subscription.objects.create(pool=subscription_pool, profile=profile,
                                            token_digest='f' * 64)
SubscriptionToken.objects.create(subscription=subscription, token_digest='f' * 64,
                                 token_epoch=1)
""")
        assert seeded.returncode == 0, seeded.stderr
        bootstrap = subprocess.run(
            [
                "docker", "exec", "--env", "PGHOST=/tmp",
                "--env", "PGUSER=xray_owner", "--env", "PGDATABASE=postgres",
                "--env", "XRAY_ADMIN_DB_PASSWORD=fixture-admin",
                "--env", "XRAY_SUBSCRIPTION_DB_PASSWORD=fixture-subscription",
                "--env", "XRAY_WORKER_DB_PASSWORD=fixture-worker",
                "--env", "XRAY_OUTBOX_DB_PASSWORD=fixture-outbox",
                name, "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-f", "/roles.sql",
            ],
            capture_output=True, text=True, timeout=30, check=False,
        )
        assert bootstrap.returncode == 0, bootstrap.stderr
        probe = run_backend("""
import django
django.setup()
from django.db import connection, transaction, DatabaseError
from django.utils import timezone
from apps.identity.models import SuperAdmin, NodeAutomationSetting, NodeStatusSyncSetting
from apps.nodes.models import ManagedNode, NodeResource, NodeConfigRevision, HostKeyRecord
from apps.nodes.tasks import (schedule_node_pool_sync, schedule_node_status_refreshes,
                              schedule_daily_node_restart, schedule_node_bootstrap)
from apps.subscriptions.models import (AccessProfile, UsageCheckpoint, Subscription,
                                      SubscriptionRevision)
from apps.subscriptions.policy import UsageService
from apps.subscriptions.publishing import Publisher
from apps.subscriptions.tasks import refresh_usage_and_limits
from apps.operations.services import ActionPreviewService
from apps.operations.models import Operation, OperationStep
from apps.subscriptions.security_events import SecurityLedger
node = ManagedNode.objects.get(deterministic_name='fixture-node')
assert schedule_node_pool_sync()['created'] == 1
assert schedule_node_status_refreshes()['scheduled'] == 1
with transaction.atomic():
    ManagedNode.objects.select_for_update().select_related(
        'cloud_account', 'cloud_credential_version').get(pk=node.pk)
assert schedule_node_bootstrap()['scheduled'] == 0
assert schedule_daily_node_restart()['scheduled'] == 0
profile = AccessProfile.objects.get(name='fixture-profile')
UsageService.record(node, epoch='fixture-epoch', sequence=1,
    samples={str(profile.pk): (17, 29)}, sampled_at=timezone.now())
profile.refresh_from_db()
assert (profile.upload_bytes, profile.download_bytes) == (17, 29)
assert UsageCheckpoint.objects.get(node=node, profile=profile).sequence == 1
resource = NodeResource.objects.create(node=node, kind='instance', external_id='fixture',
                                       ownership_tags={})
resource.cost_status = 'ACTIVE'
resource.save(update_fields=['cost_status'])
HostKeyRecord.objects.create(node=node, fingerprint='fixture-fingerprint', source='fixture')
NodeConfigRevision.objects.create(node=node, generation=1, config_hash='fixture',
    xray_version='fixture', installer_version='fixture', bundle_hash='fixture')
subscription = Subscription.objects.get(profile=profile)
revision = Publisher.publish(subscription.pk)
assert revision.usable and revision.payloads and revision.node_versions
node.addresses = [dict(family=4, value='192.0.2.11')]
node.save(update_fields=['addresses'])
assert Publisher.refresh_node_address(node.pk) == dict(published=1, failed=0)
revision.refresh_from_db()
assert revision.usable is False
subscription.refresh_from_db()
updated_revision = subscription.current_revision
assert any(value['host'] == '192.0.2.11' for value in updated_revision.node_versions.values())
batch = Publisher.invalidate_node(node.pk)
assert batch.status == 'PARTIALLY_SUCCEEDED'
assert batch.result['failures'][0]['code'] == 'NO_PUBLISHABLE_ENDPOINTS'
updated_revision.refresh_from_db()
assert updated_revision.usable is False
preview = ActionPreviewService.create(admin=SuperAdmin.objects.get(singleton_key=1),
    kind='node.delete', target_id=node.pk, params={}, required_phrase='fixture')
assert preview.pk
OperationStep.objects.create(operation=Operation.objects.order_by('created_at').first(),
                             name='fixture', phase='READ', status='SUCCEEDED')
assert SecurityLedger.append(kind='FIXTURE_PERMISSION_PROBE')['kind'] == 'FIXTURE_PERMISSION_PROBE'
result = refresh_usage_and_limits()
assert result['unavailable'] == 1
for sql in (
    "UPDATE identity_superadmin SET username='mutated'",
    "UPDATE cloud_accounts_cloudaccount SET enabled=false",
    "UPDATE cloud_accounts_cloudcredentialversion SET encrypted_credentials='{}'::jsonb",
    "UPDATE nodes_nodepool SET quota=100",
    "UPDATE nodes_nodepoolregionallocation SET quota=100",
    "DELETE FROM audit_auditevent",
    "DELETE FROM subscriptions_securityeventrecord",
):
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql)
    except DatabaseError:
        pass
    else:
        raise AssertionError('worker gained forbidden control mutation')
print('worker-runtime-role-passed')
""", user="xray_worker")
        assert probe.returncode == 0, probe.stderr
        assert probe.stdout.strip() == "worker-runtime-role-passed"
    finally:
        subprocess.run(["docker", "stop", "--time", "1", name], capture_output=True, check=False)
