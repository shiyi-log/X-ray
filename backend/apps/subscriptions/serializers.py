from __future__ import annotations


def profile_representation(profile) -> dict:
    subscription = getattr(profile, "subscription", None)
    credential_count = profile.node_credentials.filter(revoked_at__isnull=True).count()
    return {
        "id": str(profile.pk),
        "name": profile.name,
        "status": profile.status,
        "publishing_frozen": profile.publishing_frozen,
        "credential_count": credential_count,
        "subscription_id": str(subscription.pk) if subscription else None,
        "subscription_status": subscription.status if subscription else None,
        "revoked_at": profile.revoked_at.isoformat() if profile.revoked_at else None,
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
    }


def subscription_representation(subscription) -> dict:
    revision = subscription.current_revision
    return {
        "id": str(subscription.pk),
        "profile_id": str(subscription.profile_id),
        "profile_name": subscription.profile.name,
        "profile_status": subscription.profile.status,
        "status": subscription.status,
        "token_epoch": subscription.token_epoch,
        "current_revision": revision.number if revision else None,
        "public_version": revision.public_version if revision else None,
        "revision_usable": revision.usable if revision else False,
        "formats": sorted(revision.payloads) if revision else [],
        "unavailable_reasons": revision.unavailable_reasons if revision else {},
        "created_at": subscription.created_at.isoformat(),
        "updated_at": subscription.updated_at.isoformat(),
    }
