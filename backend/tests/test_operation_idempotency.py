from uuid import uuid4

import pytest
from django.utils import timezone

from common.errors import DomainError


@pytest.mark.django_db
def test_same_idempotency_key_returns_original_and_changed_params_conflict(admin):
    from apps.operations.models import OutboxEvent
    from apps.operations.services import OperationService

    target_id = uuid4()
    key = uuid4()
    request = {
        "kind": "node.inspect",
        "target_id": target_id,
        "params": {"region": "us-east-1"},
        "key": key,
        "preview_id": None,
        "admin": admin,
    }

    first = OperationService.submit(**request)
    repeated = OperationService.submit(**request)

    assert repeated.pk == first.pk
    assert OutboxEvent.objects.filter(operation=first).count() == 1

    with pytest.raises(DomainError) as caught:
        OperationService.submit(
            **{**request, "params": {"region": "ap-southeast-1"}}
        )
    assert caught.value.code == "IDEMPOTENCY_CONFLICT"


@pytest.mark.django_db
def test_preview_is_bound_to_parameters_confirmation_and_single_operation(admin):
    from apps.operations.models import ActionPreview
    from apps.operations.services import ActionPreviewService, OperationService

    target_id = uuid4()
    params = {"generation": 7, "confirmation": "DELETE NODE"}
    preview = ActionPreviewService.create(
        admin=admin,
        kind="node.delete",
        target_id=target_id,
        params=params,
        snapshot={"generation": 7, "estimated_monthly_cost": "5.00"},
        required_phrase="DELETE NODE",
    )

    operation = OperationService.submit(
        kind="node.delete",
        target_id=target_id,
        params=params,
        key=uuid4(),
        preview_id=preview.pk,
        admin=admin,
    )
    preview.refresh_from_db()
    assert operation.preview_id == preview.pk
    assert preview.consumed_at is not None

    with pytest.raises(DomainError) as caught:
        OperationService.submit(
            kind="node.delete",
            target_id=target_id,
            params=params,
            key=uuid4(),
            preview_id=preview.pk,
            admin=admin,
        )
    assert caught.value.code == "PREVIEW_EXPIRED"

    expired = ActionPreviewService.create(
        admin=admin,
        kind="node.delete",
        target_id=target_id,
        params=params,
        required_phrase="DELETE NODE",
    )
    ActionPreview.objects.filter(pk=expired.pk).update(expires_at=timezone.now())
    with pytest.raises(DomainError) as caught:
        OperationService.submit(
            kind="node.delete",
            target_id=target_id,
            params=params,
            key=uuid4(),
            preview_id=expired.pk,
            admin=admin,
        )
    assert caught.value.code == "PREVIEW_EXPIRED"


@pytest.mark.django_db
def test_preview_requires_exact_confirmation_when_phrase_is_configured(admin):
    from apps.operations.services import ActionPreviewService, OperationService

    target_id = uuid4()
    expected_params = {"generation": 3, "confirmation": "REINSTALL NODE"}
    preview = ActionPreviewService.create(
        admin=admin,
        kind="node.reinstall",
        target_id=target_id,
        params=expected_params,
        required_phrase="REINSTALL NODE",
    )

    with pytest.raises(DomainError) as caught:
        OperationService.submit(
            kind="node.reinstall",
            target_id=target_id,
            params={"generation": 3, "confirmation": "wrong"},
            key=uuid4(),
            preview_id=preview.pk,
            admin=admin,
        )
    assert caught.value.code in {"PREVIEW_STALE", "CONFIRMATION_MISMATCH"}
