#!/usr/bin/env python3
"""Load node-owned PEM files into the protected config handed to systemd."""

import json
import os
import sys
from pathlib import Path


def inline(config, directory):
    directory = directory.resolve()
    for inbound in config.get("inbounds", []):
        tls = inbound.get("streamSettings", {}).get("tlsSettings", {})
        for certificate in tls.get("certificates", []):
            for source, target in (("certificateFile", "certificate"), ("keyFile", "key")):
                if source not in certificate:
                    continue
                path = Path(certificate[source]).resolve(strict=True)
                if (
                    not path.is_relative_to(directory)
                    or not path.is_file()
                    or path.stat().st_size > 131072
                ):
                    raise ValueError("invalid managed certificate path")
                certificate[target] = path.read_text().splitlines()
                del certificate[source]
    return config


if __name__ == "__main__":
    try:
        path = Path(sys.argv[1])
        result = inline(
            json.loads(path.read_text()),
            Path(os.environ.get("XRAY_TLS_CERT_DIR", "/usr/local/etc/xray/certs")),
        )
        path.write_text(json.dumps(result, separators=(",", ":")))
        path.chmod(0o600)
    except Exception:
        # Never include PEM material or file exceptions in output.
        sys.exit(1)
