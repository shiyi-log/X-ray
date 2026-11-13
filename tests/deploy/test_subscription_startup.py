from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_subscription_loads_production_with_its_own_signing_key(tmp_path):
    image = os.getenv("XRAY_BACKEND_TEST_IMAGE")
    if not image:
        pytest.skip("XRAY_BACKEND_TEST_IMAGE is required for subscription startup")
    resolved = subprocess.run(
        [
            "docker", "compose", "--env-file",
            str(ROOT / "deploy/compose/config.example.env"),
            "-f", str(ROOT / "deploy/compose/production.yml"),
            "config", "--format", "json",
        ],
        text=True, capture_output=True, check=True,
    )
    service = json.loads(resolved.stdout)["services"]["subscription-api"]
    args = [
        "docker", "run", "--rm", "--network", "none", "--read-only",
        "--workdir", "/app/backend",
    ]
    for name, value in service["environment"].items():
        args.extend(["--env", f"{name}={value}"])
    for secret in service["secrets"]:
        source = tmp_path / secret["source"]
        source.write_text(f"fixture-only-{secret['source']}\n", encoding="utf-8")
        source.chmod(0o444)
        target = secret["target"]
        if not target.startswith("/"):
            target = f"/run/secrets/{target}"
        args.extend(["--mount", f"type=bind,src={source},dst={target},readonly"])
    args.extend([image, "python", "-c", """
import json
import os
import django
django.setup()
from django.conf import settings
from django.core.signing import Signer
value = Signer().sign('fixture-value')
print(json.dumps({
    'independent_signing_key': settings.SECRET_KEY ==
        'fixture-only-subscription_django_secret_key',
    'signing_roundtrip': Signer().unsign(value) == 'fixture-value',
    'database_user': settings.DATABASES['default']['USER'],
    'urlconf': settings.ROOT_URLCONF,
    'control_secret': os.path.exists('/run/secrets/control_master_key'),
    'cloud_secret': os.path.exists('/run/secrets/cloud_credentials'),
}))
"""])
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "independent_signing_key": True,
        "signing_roundtrip": True,
        "database_user": "xray_subscription_reader",
        "urlconf": "config.subscription_urls",
        "control_secret": False,
        "cloud_secret": False,
    }
