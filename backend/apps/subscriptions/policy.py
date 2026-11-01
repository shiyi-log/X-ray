from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from common.errors import DomainError

from .models import AccessProfile, UsageCheckpoint


def quota_state(profile, *, now=None) -> str:
    if profile.status != "ACTIVE":
        return profile.status
    return "ACTIVE"


def assert_entitled(profile):
    state = quota_state(profile)
    if state != "ACTIVE":
        raise DomainError("SUBSCRIPTION_" + state, "订阅已到期、超额或撤销", status_code=403)


def positive_integer(value, field, *, nullable=True):
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 2**63 - 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def update_policy(profile, payload):
    allowed = {"name"}
    if set(payload) - allowed:
        raise ValueError("subscription policy is unlimited; only name can be changed")
    if profile.status != "ACTIVE":
        raise DomainError("PROFILE_NOT_ACTIVE", "已撤销身份不能恢复", status_code=409)
    if "name" in payload:
        name = str(payload["name"]).strip()
        if not name or len(name) > 120:
            raise ValueError("name must contain 1 to 120 characters")
        profile.name = name
    profile.save()
    return profile


class UsageService:
    """Consume authenticated cumulative counters, never browser-supplied usage."""

    @staticmethod
    def record(node, *, epoch, sequence, samples, sampled_at):
        if not isinstance(epoch, str) or not epoch or len(epoch) > 120:
            raise ValueError("invalid usage epoch")
        positive_integer(sequence, "sequence", nullable=False)
        if (
            sampled_at is None
            or timezone.is_naive(sampled_at)
            or sampled_at > timezone.now() + timedelta(seconds=30)
        ):
            raise ValueError("invalid usage sample time")
        with transaction.atomic():
            # Serialize all snapshots of the node, including the first checkpoint.
            type(node).objects.select_for_update().get(pk=node.pk)
            for profile_id, values in sorted(samples.items()):
                profile = AccessProfile.objects.select_for_update().get(pk=profile_id)
                if not profile.node_credentials.filter(node=node).exists():
                    raise ValueError("usage profile is not assigned to node")
                upload, download = values
                if any(
                    isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 2**63 - 1
                    for v in values
                ):
                    raise ValueError("invalid cumulative counters")
                checkpoint, created = UsageCheckpoint.objects.select_for_update().get_or_create(
                    node=node,
                    profile=profile,
                    epoch=epoch,
                    defaults={"sampled_at": sampled_at},
                )
                if not created and sequence <= checkpoint.sequence:
                    continue
                if not created and sampled_at < checkpoint.sampled_at:
                    raise ValueError("usage sample moved backwards")
                if upload < checkpoint.upload_bytes or download < checkpoint.download_bytes:
                    raise ValueError("counter reset requires a new epoch")
                profile.upload_bytes += upload - checkpoint.upload_bytes
                profile.download_bytes += download - checkpoint.download_bytes
                profile.usage_updated_at = max(profile.usage_updated_at or sampled_at, sampled_at)
                profile.save(
                    update_fields=[
                        "upload_bytes",
                        "download_bytes",
                        "usage_updated_at",
                        "updated_at",
                    ]
                )
                checkpoint.sequence = sequence
                checkpoint.upload_bytes, checkpoint.download_bytes = upload, download
                checkpoint.sampled_at = sampled_at
                checkpoint.save()
