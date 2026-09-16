from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from common.errors import DomainError
from providers.base import AccountRef, MutationPermit


@pytest.mark.django_db
def test_old_worker_fence_is_rejected_after_reclaim(admin, cloud_account):
    from apps.operations.claims import assert_current, claim_operation
    from apps.operations.models import Operation
    from apps.operations.services import OperationService

    operation = OperationService.submit(
        kind="node.create",
        target_id=uuid4(),
        params={"region": "us-east-1"},
        key=uuid4(),
        preview_id=None,
        admin=admin,
        cloud_credential_version=cloud_account.credential_versions.get(version=1),
    )
    first = claim_operation(operation.pk, worker_id="worker-a", lease_seconds=60)
    Operation.objects.filter(pk=operation.pk).update(lease_expires_at=timezone.now())
    second = claim_operation(operation.pk, worker_id="worker-b", lease_seconds=60)

    with pytest.raises(DomainError) as caught:
        assert_current(first)
    assert caught.value.code == "STALE_OPERATION_FENCE"
    assert assert_current(second).pk == operation.pk
    assert second.fence > first.fence


@pytest.mark.django_db
def test_database_authorizer_binds_operation_account_region_and_credential_version(
    admin, cloud_account
):
    from apps.operations.authorization import DatabaseWriteAuthorizer
    from apps.operations.claims import claim_operation
    from apps.operations.services import OperationService

    credential = cloud_account.credential_versions.get(version=1)
    operation = OperationService.submit(
        kind="node.create",
        target_id=uuid4(),
        params={"region": "us-east-1", "account_id": str(cloud_account.pk)},
        key=uuid4(),
        preview_id=None,
        admin=admin,
        cloud_credential_version=credential,
    )
    claim = claim_operation(operation.pk, worker_id="worker-a")
    account = AccountRef(
        cloud_account.pk,
        "aws_lightsail",
        cloud_account.external_account_id,
        credential.version,
    )
    permit = MutationPermit(
        operation_id=operation.pk,
        operation_key=str(operation.idempotency_key),
        action="create",
        account_id=account.id,
        external_account_id=account.external_account_id,
        region="us-east-1",
        resource_id=None,
        expires_at=timezone.now() + timedelta(minutes=1),
        fence=claim.fence,
    )
    authorizer = DatabaseWriteAuthorizer(claim)
    authorizer.assert_allowed(permit, action="create", account=account, resource_id=None)

    wrong_region = MutationPermit(
        operation_id=operation.pk,
        operation_key=str(operation.idempotency_key),
        action="create",
        account_id=account.id,
        external_account_id=account.external_account_id,
        region="eu-west-1",
        resource_id=None,
        expires_at=timezone.now() + timedelta(minutes=1),
        fence=claim.fence,
    )
    with pytest.raises(DomainError) as caught:
        authorizer.assert_allowed(
            wrong_region, action="create", account=account, resource_id=None
        )
    assert caught.value.code == "CLOUD_WRITE_NOT_AUTHORIZED"

    wrong_resource = MutationPermit(
        operation_id=operation.pk,
        operation_key=str(operation.idempotency_key),
        action="create",
        account_id=account.id,
        external_account_id=account.external_account_id,
        region="us-east-1",
        resource_id="unexpected-resource",
        expires_at=timezone.now() + timedelta(minutes=1),
        fence=claim.fence,
    )
    with pytest.raises(DomainError) as caught:
        authorizer.assert_allowed(
            wrong_resource, action="create", account=account, resource_id=None
        )
    assert caught.value.code == "CLOUD_WRITE_NOT_AUTHORIZED"
