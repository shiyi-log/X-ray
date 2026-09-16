from uuid import uuid4

import pytest

from common.errors import DomainError
from providers.base import FirewallRule

from .test_node_lifecycle import make_lifecycle


def prepare_quarantine(admin, node, create_operation):
    from apps.operations.services import OperationService

    return OperationService.submit(
        kind="node.quarantine",
        target_id=node.pk,
        params={
            "region": node.region,
            "account_id": str(node.cloud_account_id),
            "confirmation": "QUARANTINE NODE",
        },
        key=uuid4(),
        preview_id=None,
        admin=admin,
        cloud_credential_version=node.cloud_credential_version,
    )


@pytest.mark.django_db
def test_firewall_ack_alone_is_not_isolation(admin, prepared_node):
    node, create_operation = prepared_node
    lifecycle, holder = make_lifecycle(node, probe=lambda _node: {})
    lifecycle.create(node.pk, operation_id=create_operation.pk)
    operation = prepare_quarantine(admin, node, create_operation)

    result = lifecycle.quarantine(node.pk, operation_id=operation.pk)

    node.refresh_from_db()
    assert holder["provider"].firewall_ack is True
    assert result.confirmed is False
    assert node.security_state == "ISOLATION_UNCONFIRMED"


@pytest.mark.django_db
def test_firewall_readback_and_data_plane_are_required_for_isolation(admin, prepared_node):
    node, create_operation = prepared_node
    def probe(_node):
        return {
            "fresh_connections_blocked": True,
            "existing_sessions_closed": True,
            "positive_control": True,
        }
    lifecycle, _holder = make_lifecycle(node, probe=probe)
    lifecycle.create(node.pk, operation_id=create_operation.pk)
    operation = prepare_quarantine(admin, node, create_operation)

    result = lifecycle.quarantine(node.pk, operation_id=operation.pk)

    node.refresh_from_db()
    assert result.confirmed is True
    assert node.security_state == "QUARANTINED"


@pytest.mark.django_db
def test_broad_ipv6_rule_prevents_isolation_confirmation(admin, prepared_node):
    node, create_operation = prepared_node
    def probe(_node):
        return {
            "fresh_connections_blocked": True,
            "existing_sessions_closed": True,
            "positive_control": True,
        }
    lifecycle, holder = make_lifecycle(node, probe=probe)
    lifecycle.create(node.pk, operation_id=create_operation.pk)
    operation = prepare_quarantine(admin, node, create_operation)
    provider = holder["provider"]
    provider.get_firewall = lambda resource: __import__(
        "providers.base", fromlist=["FirewallSnapshot"]
    ).FirewallSnapshot(
        (
            FirewallRule("all", None, None, "::/0", "cidr", 6),
        ),
        __import__("django.utils.timezone", fromlist=["now"]).now(),
        "unsafe-readback",
    )

    result = lifecycle.quarantine(node.pk, operation_id=operation.pk)
    assert result.confirmed is False
    assert result.evidence["firewall_safe"] is False


@pytest.mark.django_db
def test_unsafe_security_state_cannot_be_bypassed_by_request_parameter(
    admin, prepared_node
):
    node, create_operation = prepared_node
    lifecycle, _holder = make_lifecycle(node)
    lifecycle.create(node.pk, operation_id=create_operation.pk)
    node.security_state = "REVOCATION_UNCONFIRMED"
    node.save(update_fields=["security_state", "updated_at"])
    from apps.operations.services import OperationService

    operation = OperationService.submit(
        kind="node.start",
        target_id=node.pk,
        params={
            "region": node.region,
            "account_id": str(node.cloud_account_id),
            "verified_restore": True,
        },
        key=uuid4(),
        preview_id=None,
        admin=admin,
        cloud_credential_version=node.cloud_credential_version,
    )
    with pytest.raises(DomainError) as caught:
        lifecycle.dispatch("start", node.pk, operation_id=operation.pk)
    assert caught.value.code == "RESTORE_REQUIRED"


@pytest.mark.django_db
def test_global_restore_barrier_blocks_reopening_an_open_node(admin, prepared_node):
    from apps.operations.services import OperationService
    from apps.subscriptions.security_barrier import SecurityBarrier

    node, create_operation = prepared_node
    lifecycle, _holder = make_lifecycle(node)
    lifecycle.create(node.pk, operation_id=create_operation.pk)
    operation = OperationService.submit(
        kind="node.start",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(node.cloud_account_id)},
        key=uuid4(),
        preview_id=None,
        admin=admin,
        cloud_credential_version=node.cloud_credential_version,
    )
    SecurityBarrier.enter_restore()

    with pytest.raises(DomainError) as caught:
        lifecycle.dispatch("start", node.pk, operation_id=operation.pk)
    assert caught.value.code == "RESTORE_REQUIRED"
