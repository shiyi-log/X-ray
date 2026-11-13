from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _gateway() -> dict:
    result = subprocess.run(
        [
            "docker", "compose", "--env-file",
            str(ROOT / "deploy/compose/config.example.env"),
            "--file", str(ROOT / "deploy/compose/production.yml"),
            "config", "--format", "json",
        ],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)["services"]["gateway"]


@pytest.mark.parametrize(
    ("allow_cidr", "admin_status"), [("127.0.0.1/32", 200), ("192.0.2.0/24", 403)],
)
def test_gateway_entrypoint_generates_tls_listeners_and_enforces_admin_cidr(
    tmp_path, allow_cidr, admin_status,
):
    gateway = _gateway()
    certificate = tmp_path / "certificate.pem"
    private_key = tmp_path / "private-key.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(private_key), "-out", str(certificate), "-days", "1",
            "-subj", "/CN=admin.xray.invalid", "-addext",
            "subjectAltName=DNS:admin.xray.invalid,DNS:subscription.xray.invalid",
        ],
        text=True, capture_output=True, check=True,
    )
    certificate.chmod(0o444)
    private_key.chmod(0o444)
    upstream = tmp_path / "upstream.conf.template"
    upstream.write_text(
        "server { listen 8000; location / { "
        "return 200 '$http_host|$http_x_forwarded_proto'; } }\n",
        encoding="utf-8",
    )
    upstream.chmod(0o444)
    arguments = [
        "docker", "run", "--rm", "--network", "none", "--read-only",
        "--user", gateway["user"], "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true",
    ]
    for mount in gateway["tmpfs"]:
        arguments.extend(["--tmpfs", mount])
    for source in gateway["volumes"]:
        arguments.extend([
            "--mount",
            f"type=bind,src={source['source']},dst={source['target']},readonly",
        ])
    arguments.extend([
        "--mount",
        f"type=bind,src={upstream},dst=/etc/nginx/templates/upstream.conf.template,readonly",
    ])
    for secret in gateway["secrets"]:
        source = private_key if secret["source"].endswith("_key") else certificate
        target = secret["target"]
        if not target.startswith("/"):
            target = f"/run/secrets/{target}"
        arguments.extend(["--mount", f"type=bind,src={source},dst={target},readonly"])
    for host in ("admin-api", "subscription-api", "frontend"):
        arguments.extend(["--add-host", f"{host}:127.0.0.1"])
    for key, value in gateway["environment"].items():
        if key == "XRAY_ADMIN_ALLOW_CIDR":
            value = allow_cidr
        arguments.extend(["--env", f"{key}={value}"])
    probe = gateway.get("healthcheck", {}).get("test")
    assert probe is not None, "gateway health must verify a rendered TLS listener"
    assert probe[0] == "CMD-SHELL"
    arguments.extend(["--env", f"GATEWAY_HEALTH_PROBE={probe[1]}"])
    script = r"""
set -eu
if sh -c "$GATEWAY_HEALTH_PROBE"; then exit 91; fi
/docker-entrypoint.sh nginx
sh -c "$GATEWAY_HEALTH_PROBE"
admin=$(curl --silent --show-error --cacert /run/secrets/admin_tls_cert \
  --resolve admin.xray.invalid:8443:127.0.0.1 --noproxy '*' \
  --write-out '|%{http_code}' https://admin.xray.invalid:8443/health/ready | tr -d '\r\n')
subscription=$(curl --silent --show-error --cacert /run/secrets/subscription_tls_cert \
  --resolve subscription.xray.invalid:9443:127.0.0.1 --noproxy '*' \
  --write-out '|%{http_code}' https://subscription.xray.invalid:9443/health/live | tr -d '\r\n')
token_path=$(printf '%043d' 0)
token=$(curl --silent --show-error --cacert /run/secrets/subscription_tls_cert \
  --resolve subscription.xray.invalid:9443:127.0.0.1 --noproxy '*' \
  --write-out '|%{http_code}' "https://subscription.xray.invalid:9443/s/$token_path" | tr -d '\r\n')
malformed=$(curl --silent --show-error --cacert /run/secrets/subscription_tls_cert \
  --resolve subscription.xray.invalid:9443:127.0.0.1 --noproxy '*' \
  --output /dev/null --write-out '%{http_code}' https://subscription.xray.invalid:9443/s/fixture)
printf 'ADMIN_RESULT=%s\nSUBSCRIPTION_RESULT=%s\nTOKEN_RESULT=%s\nMALFORMED_RESULT=%s\n' \
  "$admin" "$subscription" "$token" "$malformed"
"""
    arguments.extend([gateway["image"], "sh", "-ec", script])
    result = subprocess.run(arguments, text=True, capture_output=True, check=False, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    admin = next(line.removeprefix("ADMIN_RESULT=") for line in result.stdout.splitlines()
                 if line.startswith("ADMIN_RESULT="))
    subscription = next(
        line.removeprefix("SUBSCRIPTION_RESULT=") for line in result.stdout.splitlines()
        if line.startswith("SUBSCRIPTION_RESULT=")
    )
    assert admin.endswith(f"|{admin_status}")
    if admin_status == 200:
        assert admin == "admin.xray.invalid|https|200"
    assert subscription == "subscription.xray.invalid|https|200"
    assert "TOKEN_RESULT=subscription.xray.invalid|https|200" in result.stdout.splitlines()
    assert "MALFORMED_RESULT=404" in result.stdout.splitlines()
