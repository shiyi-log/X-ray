import pytest

from common.errors import DomainError


@pytest.mark.django_db
def test_generation_must_be_strictly_monotonic(prepared_node):
    from apps.nodes.executor import NodeExecutor

    node, operation = prepared_node
    node.desired_generation = 9
    node.applied_generation = 9
    node.save(update_fields=["desired_generation", "applied_generation", "updated_at"])
    executor = NodeExecutor(transport_factory=lambda _node: None)
    with pytest.raises(DomainError) as caught:
        executor.apply_config(
            node.pk,
            generation=9,
            config={},
            operation_id=operation.pk,
        )
    assert caught.value.code == "STALE_CONFIG_GENERATION"
