from uuid import uuid4

import pytest

from providers.base import AccountRef

from .fakes import FakeCloudProvider


def make_lifecycle(node, *, probe=None):
    from apps.nodes.lifecycle import NodeLifecycle

    holder = {}

    def build(candidate, authorizer):
        if "provider" not in holder:
            account = AccountRef(
                candidate.cloud_account_id,
                candidate.cloud_account.provider,
                candidate.cloud_account.external_account_id,
                candidate.cloud_credential_version.version,
            )
            holder["provider"] = FakeCloudProvider(account, candidate.region, authorizer=authorizer)
        else:
            holder["provider"].authorizer = authorizer
        return holder["provider"]

    return NodeLifecycle(provider_factory=build, isolation_probe=probe), holder


@pytest.mark.django_db
def test_fake_lifecycle_adopts_read_after_write(prepared_node):
    node, operation = prepared_node
    lifecycle, holder = make_lifecycle(node)

    lifecycle.create(node.pk, operation_id=operation.pk)

    node.refresh_from_db()
    operation.refresh_from_db()
    assert holder["provider"].create_calls == 1
    assert node.external_id == node.deterministic_name
    assert node.provisioning_state == "PROVISIONED"
    assert node.resources.filter(kind="instance", external_id=node.external_id).exists()
    assert operation.status == "SUCCEEDED"


@pytest.mark.django_db
@pytest.mark.parametrize("provider", ["aws_lightsail", "aliyun_swas"])
def test_both_provider_kinds_use_same_lifecycle_contract(
    admin, cloud_account, provider
):
    from apps.nodes.models import NodePool
    from apps.nodes.quota import reserve_node
    from apps.operations.services import OperationService

    cloud_account.provider = provider
    cloud_account.external_account_id = f"fake-{provider}"
    cloud_account.save(update_fields=["provider", "external_account_id", "updated_at"])
    pool = NodePool.objects.create(name=f"pool-{provider}", region="test-region", quota=1)
    key = uuid4()
    node = reserve_node(
        pool.pk,
        account_id=cloud_account.pk,
        region="test-region",
        plan_id="small",
        image_id="debian-12",
        operation_key=key,
    )
    operation = OperationService.submit(
        kind="node.create",
        target_id=node.pk,
        params={"region": node.region, "account_id": str(cloud_account.pk)},
        key=key,
        preview_id=None,
        admin=admin,
        cloud_credential_version=node.cloud_credential_version,
    )
    lifecycle, _holder = make_lifecycle(node)
    lifecycle.create(node.pk, operation_id=operation.pk)
    node.refresh_from_db()
    assert node.provisioning_state == "PROVISIONED"
