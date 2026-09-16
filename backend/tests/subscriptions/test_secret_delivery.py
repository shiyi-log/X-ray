import pytest


@pytest.mark.django_db
def test_delivery_receipt_cannot_recover_raw_token():
    from apps.subscriptions.delivery import DeliveryService
    from apps.subscriptions.models import AccessProfile, SecretDeliveryReceipt

    profile = AccessProfile.objects.create(name="one-time", status="ACTIVE")
    delivery = DeliveryService.issue(profile.pk)
    receipt = SecretDeliveryReceipt.objects.get(subscription_id=delivery.subscription_id)

    assert delivery.raw_token
    assert not hasattr(receipt, "raw_token")
    assert delivery.raw_token not in repr(receipt.__dict__)
    with pytest.raises(LookupError):
        DeliveryService.retrieve(receipt.pk)


@pytest.mark.django_db
def test_rotation_creates_new_receipt_without_storing_secret():
    from apps.subscriptions.delivery import DeliveryService
    from apps.subscriptions.models import AccessProfile, SecretDeliveryReceipt

    profile = AccessProfile.objects.create(name="rotate-delivery", status="ACTIVE")
    first = DeliveryService.issue(profile.pk)
    second = DeliveryService.rotate(first.subscription_id)
    assert first.raw_token != second.raw_token
    serialized = repr(list(SecretDeliveryReceipt.objects.values()))
    assert first.raw_token not in serialized
    assert second.raw_token not in serialized
