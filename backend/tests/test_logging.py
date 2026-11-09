from __future__ import annotations

import logging

from common.logging import SecretMaskFilter


def test_secret_mask_filter_redacts_public_subscription_path() -> None:
    token = "a" * 43
    record = logging.LogRecord(
        name="django.server",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='"%s" %s %s',
        args=(f"GET /s/{token} HTTP/1.1", 410, 24),
        exc_info=None,
    )

    SecretMaskFilter().filter(record)

    rendered = record.getMessage()
    assert "/s/[REDACTED]" in rendered
    assert token not in rendered
