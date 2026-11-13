from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("service_name", ["admin-api", "worker"])
def test_production_issues_links_on_public_subscription_origin(service_name):
    resolved = subprocess.run(
        [
            "docker", "compose", "--env-file",
            str(ROOT / "deploy/compose/config.example.env"),
            "--file", str(ROOT / "deploy/compose/production.yml"),
            "config", "--format", "json",
        ],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    service = json.loads(resolved.stdout)["services"][service_name]
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith("XRAY_") and key != "DJANGO_SETTINGS_MODULE"
    }
    environment.update(service["environment"])
    environment.update({
        "XRAY_SECRET_KEY": "fixture-only-subscription-url-probe",
        "XRAY_DATABASE_URL": "postgresql://fixture@127.0.0.1/xray",
        "PYTHONPATH": str(ROOT / "backend"),
    })
    result = subprocess.run(
        [sys.executable, "-c", """
import json
from types import SimpleNamespace
from uuid import UUID
from urllib.parse import urlsplit
import django
django.setup()
from django.test import RequestFactory
from apps.subscriptions.admin_views import _secret_response
request = RequestFactory().post(
    '/api/v1/access-profiles/fixture/subscription/',
    HTTP_HOST='admin.xray.invalid:8443', HTTP_X_FORWARDED_PROTO='https',
)
issued = SimpleNamespace(
    subscription_id=UUID('00000000-0000-0000-0000-000000000001'),
    raw_token='fixture-only-not-a-live-token',
)
response = _secret_response(issued, request)
payload = json.loads(response.content)
url = urlsplit(payload['url'])
print(json.dumps({
    'status': response.status_code,
    'origin': url.scheme + '://' + url.netloc,
    'path_is_subscription': url.path == '/s/fixture-only-not-a-live-token',
    'cache_control': response['Cache-Control'],
    'display_once': payload['display_once'],
}))
"""],
        cwd=ROOT, env=environment, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "status": 201,
        "origin": "https://subscription.xray.invalid",
        "path_is_subscription": True,
        "cache_control": "no-store",
        "display_once": True,
    }
