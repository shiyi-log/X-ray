#!/usr/bin/env python3
"""Extract only the pinned Xray test binary from its verified archive."""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()

    try:
        with zipfile.ZipFile(args.archive) as bundle:
            try:
                member = bundle.getinfo("xray")
            except KeyError:
                print("missing fixed xray binary member", file=sys.stderr)
                return 1
            if member.is_dir():
                print("fixed xray binary member is a directory", file=sys.stderr)
                return 1
            with bundle.open(member) as source, (args.destination / "xray").open("wb") as target:
                shutil.copyfileobj(source, target)
    except (OSError, zipfile.BadZipFile) as exc:
        print(f"cannot extract fixed xray binary: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
