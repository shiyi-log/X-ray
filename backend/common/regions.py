from __future__ import annotations

DEFAULT_REGION = "ap-southeast-1"

# Regions exposed by node-pool allocation controls. Provider capability checks
# still decide whether a specific cloud account can actually use a region.
SUPPORTED_REGIONS = (
    "ap-southeast-1",
    "ap-northeast-1",
    "ap-east-1",
    "us-east-1",
    "us-west-2",
)


def is_supported_region(value: object) -> bool:
    return str(value or "").strip() in SUPPORTED_REGIONS


def normalize_region(value: object) -> str:
    """Use Singapore when a form omits or clears its optional region field."""
    region = str(value or "").strip()
    return region or DEFAULT_REGION
