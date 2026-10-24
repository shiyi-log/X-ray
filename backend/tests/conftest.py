import pytest


@pytest.fixture
def admin(db):
    from apps.identity.models import SuperAdmin

    return SuperAdmin.objects.create_superuser("owner", "test-only-password")


@pytest.fixture
def cloud_account(db):
    from django.utils import timezone

    from apps.cloud_accounts.models import CloudAccount, CloudCredentialVersion

    account = CloudAccount.objects.create(
        name="Fake AWS",
        provider="aws_lightsail",
        external_account_id="123456789012",
        credential_version=1,
        validated_at=timezone.now(),
        last_validation_code="OK",
    )
    CloudCredentialVersion.objects.create(
        account=account,
        version=1,
        encrypted_credentials={"test": "opaque"},
        identity_verified_at=timezone.now(),
    )
    return account


@pytest.fixture
def prepared_node(admin, cloud_account):
    from uuid import uuid4

    from apps.nodes.models import NodePool
    from apps.nodes.quota import reserve_node
    from apps.operations.services import OperationService

    pool = NodePool.objects.create(name=f"pool-{uuid4()}", region="us-east-1", quota=3)
    key = uuid4()
    node = reserve_node(
        pool.pk,
        account_id=cloud_account.pk,
        region="us-east-1",
        plan_id="nano",
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
    return node, operation


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient
    return APIClient()
