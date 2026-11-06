from uuid import uuid4

import pytest

from apps.nodes.models import NodeProtocol
from apps.operations.models import Operation, OperationStep
from apps.operations.services import OperationService


class _BootstrapTransport:
    def __init__(self):
        self.requests = []

    def apply(self, request):
        self.requests.append(request)
        return {
            "applied_generation": request["generation"],
            "config_test_passed": True,
            "service_restarted": True,
            "rollback_performed": False,
        }


class _BootstrapRuntime:
    def __init__(self, *, firewall_verified=True, healthy=True):
        self.firewall_verified = firewall_verified
        self.healthy = healthy
        self.firewall_rules = None
        self.transport = _BootstrapTransport()
        self.claim_contexts = []

    def install(self, _node, _manifest, *, operation_id=None, claim=None):
        self.claim_contexts.append(("install", operation_id, claim))
        return {
            "verified": True,
            "platform": "linux-amd64",
            "installer_version": "1.0.0",
            "xray_version": "26.3.27",
            "bundle_hash": "23cd9af937744d97776ee35ecad4972cf4b2109d1e0fe6be9930467608f7c8ae",
        }

    def configure_firewall(self, _node, rules, *, operation_id=None, claim=None):
        self.claim_contexts.append(("firewall", operation_id, claim))
        self.firewall_rules = rules
        return {
            "read_before_write": True,
            "write_confirmed": self.firewall_verified,
            "read_after_write": self.firewall_verified,
            "rules_verified": self.firewall_verified,
        }

    def transport_factory(self, _node):
        return self.transport

    def health_probe(self, _node):
        return {
            "accepted": self.healthy,
            "positive_control": True,
            "fresh_connection": True,
        }


def _provisioned(node, operation):
    node.external_id = node.deterministic_name
    node.raw_cloud_state = "running"
    node.addresses = [{"value": "192.0.2.20", "family": 4, "kind": "dynamic"}]
    node.provisioning_state = "PROVISIONED"
    node.save(
        update_fields=[
            "external_id",
            "raw_cloud_state",
            "addresses",
            "provisioning_state",
            "updated_at",
        ]
    )
    operation.status = "SUCCEEDED"
    operation.save(update_fields=["status", "updated_at"])


@pytest.mark.django_db
def test_bootstrap_scheduler_creates_one_operation_for_provisioned_node(prepared_node):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_node_bootstrap

    node, create_operation = prepared_node
    _provisioned(node, create_operation)
    NodeAutomationSetting.objects.create(pool_sync_enabled=True)

    first = schedule_node_bootstrap()
    second = schedule_node_bootstrap()

    assert first == {"scheduled": 1, "retried": 0, "reconciled": 0, "skipped": 0}
    assert second == {"scheduled": 0, "retried": 0, "reconciled": 0, "skipped": 1}
    bootstrap = Operation.objects.get(kind="node.bootstrap", target_id=node.pk)
    assert bootstrap.params["region"] == node.region
    assert bootstrap.params["account_id"] == str(node.cloud_account_id)


@pytest.mark.django_db
def test_bootstrap_completes_verified_node_and_publishes_active_subscription(
    prepared_node, monkeypatch
):
    import apps.nodes.bootstrap as bootstrap_module
    from apps.nodes.models import NodeConfigRevision
    from apps.subscriptions.models import AccessProfile, NodeCredential, SubscriptionRevision
    from apps.subscriptions.tokens import TokenService

    node, create_operation = prepared_node
    _provisioned(node, create_operation)
    profile = AccessProfile.objects.create(name="bootstrap-success")
    issued = TokenService.issue(profile.pk)
    bootstrap = OperationService.submit(
        kind="node.bootstrap",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(node.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=create_operation.admin,
        cloud_credential_version=node.cloud_credential_version,
    )
    runtime = _BootstrapRuntime()
    monkeypatch.setattr(
        bootstrap_module, "get_bootstrap_runtime", lambda: runtime, raising=False
    )

    from apps.operations.handlers import handle_operation

    handle_operation(str(bootstrap.pk))

    node.refresh_from_db()
    bootstrap.refresh_from_db()
    profile.subscription.refresh_from_db()
    credential = NodeCredential.objects.get(node=node, profile=profile)
    protocol = NodeProtocol.objects.get(node=node)
    revision = NodeConfigRevision.objects.get(node=node, generation=node.applied_generation)
    subscription_revision = SubscriptionRevision.objects.get(
        pk=profile.subscription.current_revision_id
    )

    assert bootstrap.status == "SUCCEEDED"
    assert bootstrap.error_code == ""
    assert node.provisioning_state == "READY"
    assert node.health_state == "HEALTHY"
    assert node.desired_generation == node.applied_generation == 1
    assert protocol.protocol == "shadowsocks"
    assert protocol.port == 8388
    assert credential.applied_generation == node.applied_generation
    assert revision.usable is True
    assert revision.probe_result["app_health_passed"] is True
    assert subscription_revision.usable is True
    assert subscription_revision.node_versions
    assert {item["host"] for item in subscription_revision.node_versions.values()} == {
        "192.0.2.20"
    }
    assert issued.subscription_id == profile.subscription.pk
    assert runtime.firewall_rules == (
        {"protocol": "tcp", "port": 8388},
        {"protocol": "udp", "port": 8388},
    )
    assert [item[0] for item in runtime.claim_contexts] == ["install", "firewall"]
    assert all(
        item[1] == bootstrap.pk and item[2].fence > 0
        for item in runtime.claim_contexts
    )
    assert len(runtime.transport.requests) == 1
    assert OperationStep.objects.filter(
        operation=bootstrap,
        name="bootstrap.publish",
        status="SUCCEEDED",
    ).exists()


@pytest.mark.django_db
def test_bootstrap_requires_firewall_write_and_readback_before_credentials(
    prepared_node, monkeypatch
):
    import apps.nodes.bootstrap as bootstrap_module
    from apps.subscriptions.models import AccessProfile, NodeCredential
    from apps.subscriptions.tokens import TokenService

    node, create_operation = prepared_node
    _provisioned(node, create_operation)
    profile = AccessProfile.objects.create(name="bootstrap-firewall-failure")
    TokenService.issue(profile.pk)
    bootstrap = OperationService.submit(
        kind="node.bootstrap",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(node.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=create_operation.admin,
        cloud_credential_version=node.cloud_credential_version,
    )
    runtime = _BootstrapRuntime(firewall_verified=False)
    monkeypatch.setattr(
        bootstrap_module, "get_bootstrap_runtime", lambda: runtime, raising=False
    )

    from apps.operations.handlers import handle_operation

    handle_operation(str(bootstrap.pk))

    node.refresh_from_db()
    bootstrap.refresh_from_db()
    assert bootstrap.status == "NEEDS_RECONCILIATION"
    assert bootstrap.error_code == "BOOTSTRAP_FIREWALL_UNVERIFIED"
    assert node.provisioning_state == "PROVISIONED"
    assert not NodeProtocol.objects.filter(node=node).exists()
    assert not NodeCredential.objects.filter(node=node).exists()
    assert profile.subscription.current_revision_id is None
    assert OperationStep.objects.filter(
        operation=bootstrap, name="bootstrap.firewall", status="UNCONFIRMED"
    ).exists()


@pytest.mark.django_db
def test_bootstrap_health_failure_never_marks_ready_or_publishes(prepared_node, monkeypatch):
    import apps.nodes.bootstrap as bootstrap_module
    from apps.subscriptions.models import AccessProfile
    from apps.subscriptions.tokens import TokenService

    node, create_operation = prepared_node
    _provisioned(node, create_operation)
    profile = AccessProfile.objects.create(name="bootstrap-health-failure")
    TokenService.issue(profile.pk)
    bootstrap = OperationService.submit(
        kind="node.bootstrap",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(node.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=create_operation.admin,
        cloud_credential_version=node.cloud_credential_version,
    )
    runtime = _BootstrapRuntime(healthy=False)
    monkeypatch.setattr(
        bootstrap_module, "get_bootstrap_runtime", lambda: runtime, raising=False
    )

    from apps.operations.handlers import handle_operation

    handle_operation(str(bootstrap.pk))

    node.refresh_from_db()
    bootstrap.refresh_from_db()
    profile.subscription.refresh_from_db()
    assert bootstrap.status == "NEEDS_RECONCILIATION"
    assert bootstrap.error_code == "NODE_HEALTH_PROBE_FAILED"
    assert node.provisioning_state == "PROVISIONED"
    assert node.health_state == "UNHEALTHY"
    assert profile.subscription.current_revision_id is None
    assert not OperationStep.objects.filter(
        operation=bootstrap, name="bootstrap.publish", status="SUCCEEDED"
    ).exists()


@pytest.mark.django_db
def test_bootstrap_stops_before_protocol_or_subscription_changes(prepared_node):
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_node_bootstrap
    from apps.operations.handlers import handle_operation
    from apps.subscriptions.models import AccessProfile, NodeCredential
    from apps.subscriptions.tokens import TokenService

    node, create_operation = prepared_node
    _provisioned(node, create_operation)
    NodeAutomationSetting.objects.create(pool_sync_enabled=True)
    profile = AccessProfile.objects.create(name="bootstrap-blocked")
    issued = TokenService.issue(profile.pk)
    revision_before = profile.subscription.current_revision_id
    generation_before = node.desired_generation
    bootstrap = OperationService.submit(
        kind="node.bootstrap",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(node.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=create_operation.admin,
        cloud_credential_version=node.cloud_credential_version,
    )

    handle_operation(str(bootstrap.pk))

    node.refresh_from_db()
    bootstrap.refresh_from_db()
    profile.subscription.refresh_from_db()
    assert bootstrap.status == "NEEDS_RECONCILIATION"
    assert bootstrap.error_code == "BOOTSTRAP_RUNTIME_UNAVAILABLE"
    assert node.provisioning_state == "PROVISIONED"
    assert node.desired_generation == generation_before
    assert not NodeProtocol.objects.filter(node=node).exists()
    assert not NodeCredential.objects.filter(node=node).exists()
    assert revision_before is None
    assert profile.subscription.current_revision_id is None
    assert issued.subscription_id == profile.subscription.pk
    assert OperationStep.objects.filter(
        operation=bootstrap, name="bootstrap.preflight", status="BLOCKED", attempt=1
    ).exists()

    assert schedule_node_bootstrap() == {
        "scheduled": 0,
        "retried": 0,
        "reconciled": 0,
        "skipped": 1,
    }
    assert Operation.objects.filter(kind="node.bootstrap", target_id=node.pk).count() == 1

    retried = OperationService.retry(bootstrap.pk, admin=create_operation.admin)
    assert retried.status == "RETRY_PENDING"
    handle_operation(str(bootstrap.pk))
    retried.refresh_from_db()
    assert retried.status == "NEEDS_RECONCILIATION"
    assert Operation.objects.filter(kind="node.bootstrap", target_id=node.pk).count() == 1
    assert OperationStep.objects.filter(
        operation=bootstrap, name="bootstrap.preflight", status="BLOCKED"
    ).count() == 2


@pytest.mark.django_db
def test_bootstrap_rejects_wrong_account_binding_without_side_effects(prepared_node):
    from apps.nodes.bootstrap import NodeBootstrapService

    node, create_operation = prepared_node
    _provisioned(node, create_operation)
    bootstrap = OperationService.submit(
        kind="node.bootstrap",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(uuid4())},
        key=uuid4(),
        preview_id=None,
        admin=create_operation.admin,
        cloud_credential_version=node.cloud_credential_version,
    )

    NodeBootstrapService.run(bootstrap.pk)

    node.refresh_from_db()
    bootstrap.refresh_from_db()
    assert bootstrap.status == "FAILED"
    assert bootstrap.error_code == "OPERATION_TARGET_MISMATCH"
    assert node.provisioning_state == "PROVISIONED"
    assert not NodeProtocol.objects.filter(node=node).exists()


@pytest.mark.django_db
def test_bootstrap_duplicate_invocation_cannot_reclaim_the_same_worker_lease(
    prepared_node, monkeypatch
):
    import apps.nodes.bootstrap as bootstrap_module
    from common.errors import DomainError

    node, create_operation = prepared_node
    _provisioned(node, create_operation)
    bootstrap = OperationService.submit(
        kind="node.bootstrap",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(node.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=create_operation.admin,
        cloud_credential_version=node.cloud_credential_version,
    )
    runtime = _BootstrapRuntime()
    original_install = runtime.install
    install_count = 0
    nested_claim_errors = []

    def install_with_duplicate(_node, manifest, *args, **kwargs):
        nonlocal install_count
        install_count += 1
        if install_count == 1:
            try:
                bootstrap_module.NodeBootstrapService.run(bootstrap.pk)
            except DomainError as exc:
                nested_claim_errors.append(exc.code)
            else:
                nested_claim_errors.append("CLAIM_ACCEPTED")
        return original_install(_node, manifest, *args, **kwargs)

    runtime.install = install_with_duplicate
    monkeypatch.setattr(bootstrap_module, "get_bootstrap_runtime", lambda: runtime)

    from apps.operations.handlers import handle_operation

    handle_operation(str(bootstrap.pk))

    bootstrap.refresh_from_db()
    assert nested_claim_errors == ["OPERATION_LEASED"]
    assert install_count == 1
    assert bootstrap.status == "SUCCEEDED"


@pytest.mark.django_db(transaction=True)
def test_bootstrap_heartbeat_renews_lease_during_long_callback(prepared_node, monkeypatch):
    import time

    from django.utils import timezone

    import apps.nodes.bootstrap as bootstrap_module
    from apps.nodes.bootstrap import _ClaimLease
    from apps.operations.claims import claim_operation, release_claim

    node, create_operation = prepared_node
    _provisioned(node, create_operation)
    bootstrap = OperationService.submit(
        kind="node.bootstrap",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(node.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=create_operation.admin,
        cloud_credential_version=node.cloud_credential_version,
    )
    claim = claim_operation(bootstrap.pk, worker_id="long-bootstrap-test", lease_seconds=2)
    lease = _ClaimLease(claim, lease_seconds=3)
    original_renew = bootstrap_module.renew_claim
    renewals = []
    renewal_errors = []

    def track_renewal(*args, **kwargs):
        try:
            renewed = original_renew(*args, **kwargs)
        except Exception as exc:
            renewal_errors.append(type(exc).__name__)
            raise
        renewals.append(renewed.expires_at)
        return renewed

    monkeypatch.setattr(bootstrap_module, "renew_claim", track_renewal)

    lease.start()
    deadline = time.monotonic() + 4
    while len(renewals) < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not renewal_errors
    assert len(renewals) >= 2
    assert renewals[-1] > claim.expires_at
    operation = lease.assert_current()
    lease.stop()
    release_claim(claim)

    assert operation.lease_owner == claim.owner
    assert operation.lease_expires_at > timezone.now()


@pytest.mark.django_db
def test_bootstrap_stops_after_installer_loses_its_fence(prepared_node, monkeypatch):
    from datetime import timedelta

    from django.db.models import F
    from django.utils import timezone

    import apps.nodes.bootstrap as bootstrap_module
    from common.errors import DomainError

    node, create_operation = prepared_node
    _provisioned(node, create_operation)
    bootstrap = OperationService.submit(
        kind="node.bootstrap",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(node.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=create_operation.admin,
        cloud_credential_version=node.cloud_credential_version,
    )
    runtime = _BootstrapRuntime()
    original_install = runtime.install

    def install_and_steal_fence(_node, manifest, *args, **kwargs):
        result = original_install(_node, manifest, *args, **kwargs)
        Operation.objects.filter(pk=bootstrap.pk).update(
            lease_owner="replacement-worker",
            lease_fence=F("lease_fence") + 1,
            lease_expires_at=timezone.now() + timedelta(minutes=4),
        )
        return result

    runtime.install = install_and_steal_fence
    monkeypatch.setattr(bootstrap_module, "get_bootstrap_runtime", lambda: runtime)

    with pytest.raises(DomainError) as error:
        bootstrap_module.NodeBootstrapService.run(bootstrap.pk)

    node.refresh_from_db()
    bootstrap.refresh_from_db()
    assert error.value.code == "STALE_OPERATION_FENCE"
    assert runtime.firewall_rules is None
    assert not NodeProtocol.objects.filter(node=node).exists()
    assert bootstrap.status == "RUNNING"
    assert bootstrap.lease_owner == "replacement-worker"


@pytest.mark.django_db
def test_bootstrap_cancel_during_installer_stops_before_next_side_effect(
    prepared_node, monkeypatch
):
    import apps.nodes.bootstrap as bootstrap_module

    node, create_operation = prepared_node
    _provisioned(node, create_operation)
    bootstrap = OperationService.submit(
        kind="node.bootstrap",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(node.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=create_operation.admin,
        cloud_credential_version=node.cloud_credential_version,
    )
    runtime = _BootstrapRuntime()
    original_install = runtime.install

    def install_and_cancel(_node, manifest, *args, **kwargs):
        result = original_install(_node, manifest, *args, **kwargs)
        cancelled = OperationService.cancel(bootstrap.pk, admin=create_operation.admin)
        assert cancelled.status == "CANCELLING"
        return result

    runtime.install = install_and_cancel
    monkeypatch.setattr(bootstrap_module, "get_bootstrap_runtime", lambda: runtime)

    bootstrap_module.NodeBootstrapService.run(bootstrap.pk)

    node.refresh_from_db()
    bootstrap.refresh_from_db()
    assert runtime.firewall_rules is None
    assert not NodeProtocol.objects.filter(node=node).exists()
    assert node.provisioning_state == "PROVISIONED"
    assert bootstrap.status == "NEEDS_RECONCILIATION"
    assert bootstrap.error_code == "BOOTSTRAP_CANCEL_REQUESTED"


@pytest.mark.django_db
def test_partial_bootstrap_publication_stays_not_ready_and_scheduler_retries(
    prepared_node, monkeypatch
):
    from datetime import timedelta

    from django.utils import timezone

    import apps.nodes.bootstrap as bootstrap_module
    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_node_bootstrap
    from apps.subscriptions import publishing as publishing_module
    from apps.subscriptions.models import AccessProfile
    from apps.subscriptions.publishing import Publisher
    from apps.subscriptions.tokens import TokenService
    from common.errors import DomainError

    node, create_operation = prepared_node
    _provisioned(node, create_operation)
    first_profile = AccessProfile.objects.create(name="bootstrap-publish-first")
    second_profile = AccessProfile.objects.create(name="bootstrap-publish-second")
    TokenService.issue(first_profile.pk)
    TokenService.issue(second_profile.pk)
    bootstrap = OperationService.submit(
        kind="node.bootstrap",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(node.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=create_operation.admin,
        cloud_credential_version=node.cloud_credential_version,
    )
    runtime = _BootstrapRuntime()
    monkeypatch.setattr(bootstrap_module, "get_bootstrap_runtime", lambda: runtime)
    original_publish = Publisher._publish_locked

    def fail_second_subscription(subscription, **kwargs):
        if subscription.pk == second_profile.subscription.pk:
            raise DomainError("TEST_PUBLISH_FAILURE", "test failure", status_code=409)
        return original_publish(subscription, **kwargs)

    monkeypatch.setattr(
        Publisher, "_publish_locked", staticmethod(fail_second_subscription)
    )

    from apps.operations.handlers import handle_operation

    handle_operation(str(bootstrap.pk))

    node.refresh_from_db()
    bootstrap.refresh_from_db()
    first_profile.subscription.refresh_from_db()
    second_profile.subscription.refresh_from_db()
    assert bootstrap.status == "NEEDS_RECONCILIATION"
    assert bootstrap.error_code == "BOOTSTRAP_SUBSCRIPTION_PUBLISH_FAILED"
    assert node.provisioning_state == "PROVISIONED"
    assert first_profile.subscription.current_revision_id is None
    assert second_profile.subscription.current_revision_id is None

    monkeypatch.setattr(Publisher, "_publish_locked", staticmethod(original_publish))
    NodeAutomationSetting.objects.create(
        pool_sync_enabled=True, pool_sync_interval_minutes=5
    )
    Operation.objects.filter(pk=bootstrap.pk).update(
        updated_at=timezone.now() - timedelta(minutes=6)
    )

    monkeypatch.setattr(
        publishing_module, "node_publish_ready", lambda *_args, **_kwargs: False
    )
    blocked_retry = schedule_node_bootstrap()

    bootstrap.refresh_from_db()
    node.refresh_from_db()
    assert blocked_retry["retried"] == 1
    assert bootstrap.status == "NEEDS_RECONCILIATION"
    assert bootstrap.error_code == "BOOTSTRAP_SUBSCRIPTION_PUBLISH_FAILED"
    assert node.provisioning_state == "PROVISIONED"

    monkeypatch.setattr(
        publishing_module, "node_publish_ready", lambda *_args, **_kwargs: True
    )
    Operation.objects.filter(pk=bootstrap.pk).update(
        updated_at=timezone.now() - timedelta(minutes=6)
    )

    result = schedule_node_bootstrap()

    node.refresh_from_db()
    bootstrap.refresh_from_db()
    first_profile.subscription.refresh_from_db()
    second_profile.subscription.refresh_from_db()
    assert result["retried"] == 1
    assert bootstrap.status == "SUCCEEDED"
    assert bootstrap.error_code == ""
    assert node.provisioning_state == "READY"
    assert first_profile.subscription.current_revision_id is not None
    assert second_profile.subscription.current_revision_id is not None


@pytest.mark.django_db
def test_bootstrap_fails_closed_when_publication_readiness_changes(prepared_node, monkeypatch):
    import apps.nodes.bootstrap as bootstrap_module
    import apps.subscriptions.publishing as publishing_module

    node, create_operation = prepared_node
    _provisioned(node, create_operation)
    bootstrap = OperationService.submit(
        kind="node.bootstrap",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(node.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=create_operation.admin,
        cloud_credential_version=node.cloud_credential_version,
    )
    monkeypatch.setattr(
        bootstrap_module, "get_bootstrap_runtime", lambda: _BootstrapRuntime()
    )
    monkeypatch.setattr(
        publishing_module, "node_publish_ready", lambda *_args, **_kwargs: False
    )

    from apps.operations.handlers import handle_operation

    handle_operation(str(bootstrap.pk))

    node.refresh_from_db()
    bootstrap.refresh_from_db()
    assert bootstrap.status == "NEEDS_RECONCILIATION"
    assert bootstrap.error_code == "NODE_NOT_READY_FOR_PUBLICATION"
    assert node.provisioning_state == "PROVISIONED"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("lease_offset_minutes", "expected_reconciled"),
    [(-1, 1), (5, 0)],
)
def test_bootstrap_scheduler_reconciles_only_expired_running_leases(
    prepared_node, lease_offset_minutes, expected_reconciled
):
    from datetime import timedelta

    from django.utils import timezone

    from apps.identity.models import NodeAutomationSetting
    from apps.nodes.tasks import schedule_node_bootstrap

    node, create_operation = prepared_node
    _provisioned(node, create_operation)
    NodeAutomationSetting.objects.create(pool_sync_enabled=True)
    bootstrap = OperationService.submit(
        kind="node.bootstrap",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(node.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=create_operation.admin,
        cloud_credential_version=node.cloud_credential_version,
    )
    bootstrap.status = "RUNNING"
    bootstrap.lease_owner = "interrupted-bootstrap-worker"
    bootstrap.lease_fence = 3
    bootstrap.lease_expires_at = timezone.now() + timedelta(
        minutes=lease_offset_minutes
    )
    bootstrap.save(
        update_fields=[
            "status",
            "lease_owner",
            "lease_fence",
            "lease_expires_at",
            "updated_at",
        ]
    )

    result = schedule_node_bootstrap()

    bootstrap.refresh_from_db()
    assert result["reconciled"] == expected_reconciled
    if expected_reconciled:
        assert bootstrap.status == "NEEDS_RECONCILIATION"
        assert bootstrap.error_code == "BOOTSTRAP_LEASE_EXPIRED"
        assert bootstrap.lease_owner == ""
        assert bootstrap.lease_expires_at is None
    else:
        assert bootstrap.status == "RUNNING"
        assert bootstrap.error_code == ""
