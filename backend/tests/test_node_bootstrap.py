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

    def install(self, _node, _manifest):
        return {
            "verified": True,
            "platform": "linux-amd64",
            "installer_version": "1.0.0",
            "xray_version": "26.3.27",
            "bundle_hash": "23cd9af937744d97776ee35ecad4972cf4b2109d1e0fe6be9930467608f7c8ae",
        }

    def configure_firewall(self, _node, rules):
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

    assert first == {"scheduled": 1, "skipped": 0}
    assert second == {"scheduled": 0, "skipped": 1}
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

    assert schedule_node_bootstrap() == {"scheduled": 0, "skipped": 1}
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
