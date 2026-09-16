from __future__ import annotations

from datetime import date

from .base import Capability, ProviderKind


def capabilities_for(provider: ProviderKind, region: str) -> tuple[Capability, ...]:
    checked = date.today()
    common = (
        Capability(
            name="validate_credentials",
            status="SUPPORTED",
            regions=(region,),
            plans=(),
            evidence_url="https://docs.aws.amazon.com/lightsail/",
            checked_at=checked,
            document_verified=True,
            stub_verified=True,
            live_verified=False,
            reason="SDK contract and local stub are covered; live verification is pending.",
        ),
        Capability(
            name="create_instance",
            status="SUPPORTED",
            regions=(region,),
            plans=(),
            evidence_url="https://docs.aws.amazon.com/lightsail/",
            checked_at=checked,
            document_verified=True,
            stub_verified=True,
            live_verified=False,
            reason="Explicit administrator operation required; no live cloud write executed.",
        ),
        Capability(
            name="rotate_public_ip",
            status="UNVERIFIED" if provider == "aws_lightsail" else "UNSUPPORTED",
            regions=(region,),
            plans=(),
            evidence_url="https://www.alibabacloud.com/help/en/simple-application-server/",
            checked_at=checked,
            document_verified=provider == "aws_lightsail",
            stub_verified=provider == "aws_lightsail",
            live_verified=False,
            reason=(
                "AWS multi-step static-IP evidence is deferred to P3."
                if provider == "aws_lightsail"
                else "SWAS replacement-node flow is required; in-place rotation is disabled."
            ),
        ),
        Capability(
            name="configure_firewall",
            status="SUPPORTED",
            regions=(region,),
            plans=(),
            evidence_url="https://docs.aws.amazon.com/lightsail/",
            checked_at=checked,
            document_verified=True,
            stub_verified=True,
            live_verified=False,
            reason="Rule application and read-back are separate from data-plane isolation.",
        ),
        Capability(
            name="delete_instance",
            status="SUPPORTED",
            regions=(region,),
            plans=(),
            evidence_url="https://docs.aws.amazon.com/lightsail/",
            checked_at=checked,
            document_verified=True,
            stub_verified=True,
            live_verified=False,
            reason="Deletion remains separately authorized and is not part of local tests.",
        ),
    )
    return common
