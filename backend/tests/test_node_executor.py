from uuid import uuid4

import pytest

from common.errors import DomainError


class FakeTransport:
    def __init__(self, response=None):
        self.requests = []
        self.response = response or {
            "applied_generation": 1,
            "config_test_passed": True,
            "service_restarted": True,
            "rollback_performed": False,
            "config_hash": "remote-hash",
        }

    def apply(self, request):
        self.requests.append(request)
        return dict(self.response)


@pytest.mark.django_db
def test_executor_applies_generation_and_persists_revision(prepared_node):
    from apps.nodes.executor import NodeExecutor
    from apps.nodes.models import NodeConfigRevision

    node, operation = prepared_node
    transport = FakeTransport()
    executor = NodeExecutor(transport_factory=lambda _node: transport)
    config = {"inbounds": [], "outbounds": [{"protocol": "freedom"}]}

    result = executor.apply_config(
        node.pk,
        generation=1,
        config=config,
        operation_id=operation.pk,
    )

    node.refresh_from_db()
    assert result.applied_generation == 1
    assert result.config_test_passed is True
    assert result.config_hash == "remote-hash"
    assert node.applied_generation == 1
    assert node.desired_generation == 1
    assert NodeConfigRevision.objects.filter(node=node, generation=1, usable=True).exists()
    assert transport.requests[0]["expected_previous_generation"] == 0


@pytest.mark.django_db
def test_executor_rejects_stale_generation_before_remote_call(prepared_node):
    from apps.nodes.executor import NodeExecutor

    node, operation = prepared_node
    node.applied_generation = 5
    node.desired_generation = 5
    node.save(update_fields=["applied_generation", "desired_generation", "updated_at"])
    transport = FakeTransport()
    executor = NodeExecutor(transport_factory=lambda _node: transport)

    with pytest.raises(DomainError) as caught:
        executor.apply_config(
            node.pk,
            generation=4,
            config={"clients": ["revoked"]},
            operation_id=operation.pk,
        )
    assert caught.value.code == "STALE_CONFIG_GENERATION"
    assert transport.requests == []


@pytest.mark.django_db
def test_security_change_never_accepts_remote_rollback(prepared_node):
    from apps.nodes.executor import NodeExecutor

    node, operation = prepared_node
    response = {
        "applied_generation": 1,
        "config_test_passed": True,
        "service_restarted": False,
        "rollback_performed": True,
        "config_hash": "remote-hash",
    }
    transport = FakeTransport(response)
    executor = NodeExecutor(transport_factory=lambda _node: transport)

    with pytest.raises(DomainError) as caught:
        executor.apply_config(
            node.pk,
            generation=1,
            config={"clients": []},
            operation_id=operation.pk,
            allow_security_rollback=False,
        )
    node.refresh_from_db()
    assert caught.value.code == "SECURITY_ROLLBACK_FORBIDDEN"
    assert node.security_state == "ISOLATION_UNCONFIRMED"


@pytest.mark.django_db
def test_probe_uses_injected_evidence_runner(prepared_node):
    from apps.nodes.execution_types import ProbeResult
    from apps.nodes.executor import NodeExecutor

    node, operation = prepared_node
    credential_ref = uuid4()
    expected = ProbeResult(True, True, True, None, {"route": "node"})
    executor = NodeExecutor(
        transport_factory=lambda _node: FakeTransport(),
        probe_runner=lambda *_args, **_kwargs: expected,
    )
    assert executor.probe(
        node.pk,
        credential_ref=credential_ref,
        expect_accept=True,
        operation_id=operation.pk,
    ) == expected
