#!/usr/bin/env python3
"""Remove authentication context and network payloads from generated test traces."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path


def sanitize_trace(target: Path) -> None:
    temporary = None
    try:
        with zipfile.ZipFile(target) as source:
            descriptor, name = tempfile.mkstemp(
                prefix=".sanitized-trace-", suffix=".zip", dir=target.parent
            )
            temporary = Path(name)
            with (
                os.fdopen(descriptor, "w+b") as stream,
                zipfile.ZipFile(
                    stream, "w", compression=zipfile.ZIP_DEFLATED
                ) as output,
            ):
                for member in source.infolist():
                    if member.filename.endswith("trace.network"):
                        continue
                    data = source.read(member)
                    if member.filename.endswith(".trace"):
                        records = []
                        for line in data.decode("utf-8").splitlines():
                            if not line.strip():
                                continue
                            record = json.loads(line)
                            if not isinstance(record, dict):
                                raise ValueError("Invalid trace record")
                            options = record.get("options")
                            if isinstance(options, dict):
                                for field in (
                                    "storageState",
                                    "httpCredentials",
                                    "extraHTTPHeaders",
                                    "proxy",
                                ):
                                    options.pop(field, None)
                            records.append(json.dumps(record, ensure_ascii=False))
                        data = ("\n".join(records) + "\n").encode("utf-8")
                    output.writestr(member, data)
        os.replace(temporary, target)
        temporary = None
    except (OSError, ValueError, zipfile.BadZipFile):
        # These are run-owned generated traces. An unsafe original must never
        # survive a failed scrub and reach an always-run artifact upload.
        target.unlink(missing_ok=True)
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    arguments = parser.parse_args()
    try:
        sanitize_trace(arguments.trace)
    except (OSError, ValueError, zipfile.BadZipFile):
        print("Trace sanitization failed; unsafe artifact removed.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
