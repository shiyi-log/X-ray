from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_BEARER = "fixture_" + "a" * 35


@pytest.mark.parametrize("failure", ["rate_limit", "upstream_unavailable"])
def test_public_subscription_failures_do_not_log_the_bearer(tmp_path, failure):
    """Inherited warn-level Nginx errors must never expose a subscription path."""
    resolved = subprocess.run(
        [
            "docker", "compose", "--env-file",
            str(ROOT / "deploy/compose/config.example.env"),
            "--file", str(ROOT / "deploy/compose/production.yml"),
            "config", "--format", "json",
        ],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    gateway = json.loads(resolved.stdout)["services"]["gateway"]
    certificate, private_key = tmp_path / "certificate.pem", tmp_path / "private-key.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(private_key), "-out", str(certificate), "-days", "1",
            "-subj", "/CN=subscription.xray.invalid", "-addext",
            "subjectAltName=DNS:subscription.xray.invalid",
        ],
        text=True, capture_output=True, check=True,
    )
    certificate.chmod(0o444)
    private_key.chmod(0o444)
    arguments = [
        "docker", "run", "--rm", "--network", "none", "--read-only",
        "--user", gateway["user"], "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true",
        "--add-host", "subscription-api:127.0.0.1",
        "--env", "XRAY_SUBSCRIPTION_HOST=subscription.xray.invalid",
        "--env", f"FIXTURE_BEARER={FIXTURE_BEARER}",
    ]
    for mount in gateway["tmpfs"]:
        arguments.extend(["--tmpfs", mount])
    mounts = [
        (ROOT / "deploy/nginx/gateway.conf", "/etc/nginx/nginx.conf"),
        (ROOT / "deploy/nginx/subscription.conf", "/etc/nginx/templates/subscription.conf.template"),
        (certificate, "/run/secrets/subscription_tls_cert"),
        (private_key, "/run/secrets/subscription_tls_key"),
    ]
    if failure == "rate_limit":
        upstream = tmp_path / "upstream.conf.template"
        upstream.write_text("server { listen 8000; location / { return 200 'ok'; } }\n")
        upstream.chmod(0o444)
        mounts.append((upstream, "/etc/nginx/templates/upstream.conf.template"))
    for source, target in mounts:
        arguments.extend(["--mount", f"type=bind,src={source},dst={target},readonly"])
    script = r"""
set -eu
/docker-entrypoint.sh nginx
for attempt in 1 2 3 4 5; do
  if curl --silent --output /dev/null --cacert /run/secrets/subscription_tls_cert \
    --resolve subscription.xray.invalid:9443:127.0.0.1 --noproxy '*' \
    https://subscription.xray.invalid:9443/health/live; then break; fi
  sleep 0.1
done
for attempt in $(seq 1 16); do
  status=$(curl --silent --show-error --output /dev/null \
    --cacert /run/secrets/subscription_tls_cert \
    --resolve subscription.xray.invalid:9443:127.0.0.1 --noproxy '*' \
    --write-out '%{http_code}' "https://subscription.xray.invalid:9443/s/$FIXTURE_BEARER")
  printf 'HTTP_STATUS=%s\n' "$status"
done
"""
    arguments.extend([gateway["image"], "sh", "-ec", script])
    result = subprocess.run(arguments, text=True, capture_output=True, timeout=20, check=False)
    assert result.returncode == 0, "isolated Nginx request fixture must complete"
    statuses = [
        int(line.removeprefix("HTTP_STATUS="))
        for line in result.stdout.splitlines() if line.startswith("HTTP_STATUS=")
    ]
    if failure == "rate_limit":
        assert 200 in statuses, "the healthy upstream is a positive control"
        assert 503 in statuses, "the real production rate limit must reject requests"
    else:
        assert 502 in statuses, "an unreachable upstream must remain observable via HTTP"
    assert FIXTURE_BEARER not in result.stderr, "Nginx error logs exposed the bearer path"
    assert FIXTURE_BEARER not in result.stdout, "Nginx access logs exposed the bearer path"
