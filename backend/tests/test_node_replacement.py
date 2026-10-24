from uuid import uuid4

import pytest

from common.errors import DomainError


@pytest.mark.django_db
def test_stopped_node_still_consumes_quota_and_blocks_replacement(cloud_account):
    from apps.nodes.models import NodePool
    from apps.nodes.quota import reserve_node

    pool = NodePool.objects.create(name="replacement-full", region="us-east-1", quota=1)
    original = reserve_node(
        pool.pk,
        account_id=cloud_account.pk,
        region="us-east-1",
        plan_id="nano",
        image_id="debian-12",
        operation_key=uuid4(),
    )
    original.desired_state = "STOPPED"
    original.raw_cloud_state = "stopped"
    original.save(update_fields=["desired_state", "raw_cloud_state", "updated_at"])

    with pytest.raises(DomainError) as caught:
        reserve_node(
            pool.pk,
            account_id=cloud_account.pk,
            region="us-east-1",
            plan_id="nano",
            image_id="debian-12",
            operation_key=uuid4(),
        )
    assert caught.value.code == "POOL_QUOTA_EXCEEDED"
    original.refresh_from_db()
    assert original.consumes_quota is True
