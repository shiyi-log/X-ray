import pytest

from .test_node_lifecycle import make_lifecycle


@pytest.mark.django_db
def test_create_timeout_never_blindly_recreates(prepared_node):
    node, operation = prepared_node
    lifecycle, holder = make_lifecycle(node)
    provider = lifecycle.provider_for(node, None)
    provider.fail_after_create = True

    lifecycle.create(node.pk, operation_id=operation.pk)
    operation.refresh_from_db()
    assert provider.create_calls == 1
    assert operation.status == "NEEDS_RECONCILIATION"

    provider.fail_after_create = False
    lifecycle.reconcile(node.pk, operation_id=operation.pk)

    node.refresh_from_db()
    operation.refresh_from_db()
    assert provider.create_calls == 1
    assert provider.lookup_calls >= 2
    assert node.external_id == node.deterministic_name
    assert operation.status == "SUCCEEDED"
