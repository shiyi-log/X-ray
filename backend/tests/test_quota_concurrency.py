from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import close_old_connections, connections

from common.errors import DomainError


@pytest.mark.django_db(transaction=True)
def test_only_one_create_fits_last_pool_slot(admin, cloud_account):
    from apps.nodes.models import ManagedNode, NodePool
    from apps.nodes.quota import reserve_node

    pool = NodePool.objects.create(name="last-slot", region="us-east-1", quota=1)
    barrier = Barrier(2)

    def reserve(key):
        close_old_connections()
        barrier.wait(timeout=5)
        try:
            node = reserve_node(
                pool.pk,
                account_id=cloud_account.pk,
                region="us-east-1",
                plan_id="nano",
                image_id="debian-12",
                operation_key=key,
            )
            return ("accepted", str(node.pk))
        except DomainError as exc:
            return (exc.code, None)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, [uuid4(), uuid4()]))

    assert [result[0] for result in results].count("accepted") == 1
    assert [result[0] for result in results].count("POOL_QUOTA_EXCEEDED") == 1
    assert ManagedNode.objects.filter(pool=pool, consumes_quota=True).count() == 1


@pytest.mark.django_db
def test_quota_is_not_released_without_confirmed_cloud_absence(cloud_account):
    from apps.nodes.models import NodePool
    from apps.nodes.quota import release_quota, reserve_node

    pool = NodePool.objects.create(name="retained-resource", region="us-east-1", quota=1)
    node = reserve_node(
        pool.pk,
        account_id=cloud_account.pk,
        region="us-east-1",
        plan_id="nano",
        image_id="debian-12",
        operation_key=uuid4(),
    )
    with pytest.raises(DomainError) as caught:
        release_quota(node.pk, cloud_absence_confirmed=False)
    assert caught.value.code == "RESOURCE_ABSENCE_UNCONFIRMED"
    node.refresh_from_db()
    assert node.consumes_quota is True
