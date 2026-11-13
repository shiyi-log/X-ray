from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _production_services() -> dict:
    result = subprocess.run(
        [
            "docker", "compose",
            "--env-file", str(ROOT / "deploy/compose/config.example.env"),
            "--file", str(ROOT / "deploy/compose/production.yml"),
            "config", "--format", "json",
        ],
        cwd=ROOT, text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)["services"]


def _production_probe(service: dict, code: str) -> subprocess.CompletedProcess[str]:
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith("XRAY_") and key != "DJANGO_SETTINGS_MODULE"
    }
    environment.update(service["environment"])
    environment.update({
        "XRAY_SECRET_KEY": "fixture-only-production-settings-probe",
        "XRAY_DATABASE_URL": "postgresql://fixture@127.0.0.1/xray",
        "PYTHONPATH": str(ROOT / "backend"),
    })
    return subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=environment,
        text=True, capture_output=True, check=False,
    )


def test_production_login_and_step_up_accept_the_published_admin_origin():
    result = _production_probe(_production_services()["admin-api"], """
import json
import django
django.setup()
from django.conf import settings
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware, get_token
from django.test import RequestFactory
statuses = []
for path in ('/api/v1/auth/login', '/api/v1/auth/step-up'):
    for origin in ('https://admin.xray.invalid:8443', 'https://admin.xray.invalid',
                   'https://other.xray.invalid:8443'):
        request = RequestFactory().post(
            path, HTTP_HOST='admin.xray.invalid', HTTP_ORIGIN=origin,
            HTTP_X_FORWARDED_PROTO='https',
        )
        request.META['HTTP_X_CSRFTOKEN'] = get_token(request)
        request.COOKIES[settings.CSRF_COOKIE_NAME] = request.META['CSRF_COOKIE']
        response = CsrfViewMiddleware(lambda r: HttpResponse()).process_view(
            request, lambda r: HttpResponse(), (), {},
        )
        statuses.append(response.status_code if response is not None else 200)
print(json.dumps(statuses))
""")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [200, 200, 403, 200, 200, 403]


@pytest.mark.parametrize("service_name", ["worker", "beat"])
def test_celery_can_load_production_settings_using_only_its_mounted_secrets(
    tmp_path, service_name
):
    image = os.getenv("XRAY_BACKEND_TEST_IMAGE")
    if not image:
        pytest.skip("XRAY_BACKEND_TEST_IMAGE is required for the Celery startup gate")
    service = _production_services()[service_name]
    args = ["docker", "run", "--rm", "--network", "none", "--read-only"]
    if service.get("working_dir"):
        args.extend(["--workdir", service["working_dir"]])
    for name, value in service["environment"].items():
        args.extend(["--env", f"{name}={value}"])
    for secret in service.get("secrets", []):
        source = tmp_path / secret["source"]
        source.write_text("fixture-only-startup-value\n", encoding="utf-8")
        source.chmod(0o444)
        target = secret["target"]
        if not target.startswith("/"):
            target = f"/run/secrets/{target}"
        args.extend([
            "--mount",
            f"type=bind,src={source},dst={target},readonly",
        ])
    args.extend([image, "python", "-c", """
import json
import django
django.setup()
from django.conf import settings
from config.celery import app
print(json.dumps({
    'database_user': settings.DATABASES['default']['USER'],
    'pool_scheduler': app.conf.beat_schedule['node-pool-quota-scheduler']['task'],
    'cloud_secret_available': __import__('os').path.exists('/run/secrets/cloud_credentials'),
}))
"""])
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "database_user": "xray_worker",
        "pool_scheduler": "apps.nodes.tasks.schedule_node_pool_sync",
        "cloud_secret_available": service_name == "worker",
    }


def test_admin_health_proxy_preserves_allowed_host_and_https_without_redirect(tmp_path):
    image = os.getenv("XRAY_FRONTEND_TEST_IMAGE")
    if not image:
        pytest.skip("XRAY_FRONTEND_TEST_IMAGE is required for the nginx proxy gate")
    admin = (ROOT / "deploy/nginx/admin.conf").read_text(encoding="utf-8")
    location = re.search(r"location /health/ \{(.*?)\n    \}", admin, re.S)
    assert location is not None
    health = location.group(1).replace("http://admin-api:8000", "http://127.0.0.1:18000")
    config = tmp_path / "nginx.conf"
    config.write_text(
        "pid /tmp/nginx.pid;\nevents {}\nhttp {\n"
        "access_log off; client_body_temp_path /tmp/client; proxy_temp_path /tmp/proxy;\n"
        "fastcgi_temp_path /tmp/fastcgi; uwsgi_temp_path /tmp/uwsgi; scgi_temp_path /tmp/scgi;\n"
        "server { listen 18000; location / { return 200 '$http_host|$http_x_forwarded_proto'; } }\n"
        f"server {{ listen 18443; location /health/ {{{health}\n}} }}\n}}\n",
        encoding="utf-8",
    )
    config.chmod(0o444)
    result = subprocess.run(
        [
            "docker", "run", "--rm", "--network", "none", "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
            "--mount", f"type=bind,src={config},dst=/etc/nginx/nginx.conf,readonly",
            "--entrypoint", "/bin/sh", image, "-ec",
            "nginx; wget -qO- --header='Host: admin.xray.invalid' "
            "--header='X-Forwarded-Proto: http' http://127.0.0.1:18443/health/ready",
        ],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    host, protocol = result.stdout.split("|")
    service = _production_services()["admin-api"]
    probe = _production_probe(service, f"""
import django
django.setup()
from django.http import HttpResponse
from django.middleware.security import SecurityMiddleware
from django.test import RequestFactory
request = RequestFactory().get(
    '/health/ready', HTTP_HOST={host!r}, HTTP_X_FORWARDED_PROTO={protocol!r},
)
request.get_host()
response = SecurityMiddleware(lambda r: HttpResponse()).process_request(request)
print(response.status_code if response is not None else 200)
""")
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "200"
