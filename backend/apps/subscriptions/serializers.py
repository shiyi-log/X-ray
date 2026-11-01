from __future__ import annotations

from django.db.models import F


def profile_representation(profile) -> dict:
    from .policy import quota_state

    subscription = getattr(profile, "subscription", None)
    credential_count = (
        profile.node_credentials.filter(revoked_at__isnull=True)
        .values("node_id", "protocol_id")
        .distinct()
        .count()
    )
    return {
        "id": str(profile.pk),
        "name": profile.name,
        "status": profile.status,
        "publishing_frozen": profile.publishing_frozen,
        "plan_id": str(profile.plan_id) if profile.plan_id else None,
        "expires_at": profile.expires_at.isoformat() if profile.expires_at else None,
        "traffic_limit_bytes": profile.traffic_limit_bytes,
        "upload_bytes": profile.upload_bytes,
        "download_bytes": profile.download_bytes,
        "usage_updated_at": profile.usage_updated_at.isoformat()
        if profile.usage_updated_at
        else None,
        "entitlement_state": quota_state(profile),
        "metering_coverage": "PARTIAL"
        if profile.node_credentials.filter(
            revoked_at__isnull=True, protocol__protocol="socks5"
        ).exists()
        else "SUPPORTED",
        "access_sync_pending": profile.node_credentials.filter(revoked_at__isnull=True)
        .exclude(desired_generation=F("applied_generation"))
        .exists(),
        "credential_count": credential_count,
        "subscription_id": str(subscription.pk) if subscription else None,
        "subscription_status": subscription.status if subscription else None,
        "revoked_at": profile.revoked_at.isoformat() if profile.revoked_at else None,
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
    }


def subscription_representation(subscription) -> dict:
    revision = subscription.current_revision
    current_token_status = subscription.token_history.filter(
        token_epoch=subscription.token_epoch
    ).values_list("status", flat=True).first()
    return {
        "id": str(subscription.pk),
        "pool_id": str(subscription.pool_id),
        "pool_name": subscription.pool.name,
        "profile_id": str(subscription.profile_id),
        "profile_name": subscription.profile.name,
        "profile_status": subscription.profile.status,
        "policy": profile_representation(subscription.profile),
        "status": subscription.status,
        "current_token_status": current_token_status,
        "token_epoch": subscription.token_epoch,
        "current_revision": revision.number if revision else None,
        "public_version": revision.public_version if revision else None,
        "revision_usable": revision.usable if revision else False,
        "formats": sorted(revision.payloads) if revision else [],
        "unavailable_reasons": revision.unavailable_reasons if revision else {},
        "created_at": subscription.created_at.isoformat(),
        "updated_at": subscription.updated_at.isoformat(),
    }


def subscription_token_representation(token) -> dict:
    subscription = getattr(token, "subscription", None)
    return {
        "id": str(token.pk),
        "subscription_id": str(token.subscription_id),
        "token_epoch": token.token_epoch,
        "status": token.status,
        "is_current": bool(
            subscription
            and token.status == "ACTIVE"
            and subscription.token_epoch == token.token_epoch
            and subscription.token_digest == token.token_digest
        ),
        "revoked_at": token.revoked_at.isoformat() if token.revoked_at else None,
        "replaced_by_id": str(token.replaced_by_id) if token.replaced_by_id else None,
        "created_at": token.created_at.isoformat(),
    }
