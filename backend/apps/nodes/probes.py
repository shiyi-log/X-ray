from __future__ import annotations

import json
import os
import subprocess

from .execution_types import ProbeResult


def curl_socks5h_probe(
    *,
    proxy_host: str,
    proxy_port: int,
    username: str,
    password: str,
    target_url: str,
    timeout: int = 10,
) -> ProbeResult:
    config = "\n".join(
        [
            'silent',
            'show-error',
            'fail',
            f'max-time = {int(timeout)}',
            f'proxy = "socks5h://{proxy_host}:{int(proxy_port)}"',
            f'proxy-user = "{username}:{password}"',
            f'url = "{target_url}"',
        ]
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if key.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    }
    completed = subprocess.run(
        ["curl", "--disable", "--config", "-"],
        input=config,
        text=True,
        capture_output=True,
        env=env,
        timeout=timeout + 2,
        check=False,
    )
    return ProbeResult(
        accepted=completed.returncode == 0,
        positive_control=True,
        fresh_connection=True,
        existing_session_closed=None,
        evidence={"exit_code": completed.returncode, "route": "socks5h"},
    )


def sanitized_probe_evidence(result: ProbeResult) -> str:
    return json.dumps(result.evidence, sort_keys=True, separators=(",", ":"))
