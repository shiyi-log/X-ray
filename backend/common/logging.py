from __future__ import annotations

import logging
import re

_SECRET_PATTERN = re.compile(
    r"(?i)(password|passwd|token|secret|private[_ -]?key|authorization|cookie)="
    r"([^\s,;]+)"
)
_PUBLIC_TOKEN_PATH_PATTERN = re.compile(r"(?i)(/s/)[A-Za-z0-9_-]{20,}")


def _mask(value: str) -> str:
    value = _SECRET_PATTERN.sub(r"\1=[REDACTED]", value)
    return _PUBLIC_TOKEN_PATH_PATTERN.sub(r"\1[REDACTED]", value)


class SecretMaskFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _mask(record.msg)
        if record.args:
            record.args = tuple(
                _mask(arg)
                if isinstance(arg, str)
                else arg
                for arg in record.args
            )
        return True
