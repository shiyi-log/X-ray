from __future__ import annotations

DEFAULT_REGION = "ap-southeast-1"


def normalize_region(value: object) -> str:
    """Use Singapore when a form omits or clears its optional region field."""
    region = str(value or "").strip()
    return region or DEFAULT_REGION
