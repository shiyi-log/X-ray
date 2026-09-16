from __future__ import annotations

import logging
import re

_SECRET_PATTERN = re.compile(
    r"(?i)(password|passwd|token|secret|private[_ -]?key|authorization|cookie)="
    r"([^\s,;]+)"
)


class SecretMaskFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _SECRET_PATTERN.sub(r"\1=[REDACTED]", record.msg)
        if record.args:
            record.args = tuple(
                _SECRET_PATTERN.sub(r"\1=[REDACTED]", arg)
                if isinstance(arg, str)
                else arg
                for arg in record.args
            )
        return True
