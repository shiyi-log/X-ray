from __future__ import annotations

import json
import os
from datetime import timedelta
from uuid import uuid4

import pytest
from django.urls import include, path
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.identity.models import SuperAdmin


def upgrade_view(request):
    from apps.identity.upgrade import upgrade

    return upgrade(request)


urlpatterns = [
    path("api/v1/system/upgrade/", upgrade_view),
    path("", include("config.urls")),
]

pytestmark = pytest.mark.django_db


@pytest.fixture
def client(settings, tmp_path):
    settings.BASE_DIR = tmp_path / "backend"
    (tmp_path / "VERSION").write_text("0.14.9")
    settings.ROOT_URLCONF = __name__
    settings.ALLOWED_HOSTS = ["testserver", "127.0.0.1"]
    settings.XRAY_ENV = "test"
    settings.XRAY_LOCAL_ONE_CLICK_LOGIN = True
    SuperAdmin.objects.create_superuser("upgrade-admin", "fixture-password-only")
    client = APIClient(enforce_csrf_checks=True)
    csrf = client.get("/api/v1/auth/csrf", HTTP_HOST="127.0.0.1")
    client.credentials(HTTP_X_CSRFTOKEN=csrf.json()["csrf_token"])
    assert (
        client.post(
            "/api/v1/auth/local-login", {}, format="json", HTTP_HOST="127.0.0.1"
        ).status_code
        == 200
    )
    session = client.session
    session["recent_auth_until"] = (timezone.now() + timedelta(minutes=5)).isoformat()
    session.save()
    return client


@pytest.fixture
def upgrade_root(tmp_path, settings):
    settings.XRAY_UPGRADE_ROOT = str(tmp_path)
    (tmp_path / "requests").mkdir()
    (tmp_path / "results").mkdir()
    catalog = {
        "schema_version": 1,
        "releases": [
            {
                "version": "0.14.9",
                "published_at": "2026-11-14T00:00:00Z",
                "notes": "Current release",
            },
            {"version": "0.15.0", "published_at": "2026-11-14T00:00:00Z", "notes": "Next release"},
            {"version": "0.14.8", "published_at": "2026-11-14T00:00:00Z", "notes": "Old release"},
        ],
    }
    (tmp_path / "catalog.json").write_text(json.dumps(catalog))
    return tmp_path


def submit(client, version="0.15.0", key=None, **extra):
    return client.post(
        "/api/v1/system/upgrade/",
        {"version": version, "confirmation": "确认在线升级", **extra},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(key or uuid4()),
    )


def test_unconfigured_upgrade_is_explicitly_unavailable(client, settings):
    settings.XRAY_UPGRADE_ROOT = ""
    response = client.get("/api/v1/system/upgrade/")
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["candidates"] == []
    assert submit(client).status_code == 503


def test_catalog_lists_only_current_or_newer_versions(client, upgrade_root):
    response = client.get("/api/v1/system/upgrade/")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["current_version"] == "0.14.9"
    assert [item["version"] for item in body["candidates"]] == ["0.15.0", "0.14.9"]
    assert body["jobs"] == []


def test_submission_creates_one_atomic_request_and_audit(client, upgrade_root):
    key = uuid4()
    response = submit(client, key=key)
    assert response.status_code == 202
    job = response.json()
    assert job["id"] == str(key) and job["status"] == "QUEUED"
    request_path = upgrade_root / "requests" / f"{key}.json"
    request = json.loads(request_path.read_text())
    assert set(request) == {"schema_version", "id", "version", "created_at", "actor_id"}
    assert request["version"] == "0.15.0"
    assert os.stat(request_path).st_mode & 0o777 == 0o640
    assert list((upgrade_root / "requests").glob("*.json")) == [request_path]
    event = AuditEvent.objects.get(action="system.upgrade.submit")
    assert event.metadata == {"version": "0.15.0"}
    assert submit(client, key=key).json() == job
    assert AuditEvent.objects.filter(action="system.upgrade.submit").count() == 1


def test_same_idempotency_key_different_version_is_conflict(client, upgrade_root):
    key = uuid4()
    assert submit(client, key=key).status_code == 202
    response = submit(client, version="0.14.9", key=key)
    assert response.status_code == 409
    assert response.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_nonterminal_job_blocks_another_upgrade(client, upgrade_root):
    assert submit(client).status_code == 202
    response = submit(client)
    assert response.status_code == 409
    assert response.json()["code"] == "UPGRADE_IN_PROGRESS"
    assert len(list((upgrade_root / "requests").glob("*.json"))) == 1


def test_terminal_results_enable_next_job_and_do_not_expose_logs(client, upgrade_root):
    key = uuid4()
    assert submit(client, key=key).status_code == 202
    (upgrade_root / "results" / f"{key}.json").write_text(
        json.dumps(
            {
                "id": str(key),
                "version": "0.15.0",
                "status": "FAILED",
                "phase": "BACKUP",
                "error_code": "UPGRADE_FAILED",
                "updated_at": "2026-11-14T01:00:00Z",
                "logs": "secret-bearing-output",
                "exception": "secret-bearing-output",
            }
        )
    )
    response = client.get("/api/v1/system/upgrade/")
    assert response.status_code == 200
    assert "secret-bearing-output" not in response.content.decode()
    assert response.json()["jobs"][0]["status"] == "FAILED"
    assert submit(client).status_code == 202


@pytest.mark.parametrize(
    "version",
    ["0.14.8", "0.16.0", "../../etc/passwd", "0.15.0;id", "https://example.invalid", "01.15.0"],
)
def test_rejects_downgrade_unregistered_or_nonversion_input(client, upgrade_root, version):
    assert submit(client, version=version).status_code in {400, 409}
    assert list((upgrade_root / "requests").glob("*.json")) == []


def test_unknown_fields_bad_confirmation_and_missing_key_are_rejected(client, upgrade_root):
    assert submit(client, command="arbitrary").status_code == 400
    response = client.post(
        "/api/v1/system/upgrade/",
        {"version": "0.15.0", "confirmation": "wrong"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    assert response.status_code == 400
    response = client.post(
        "/api/v1/system/upgrade/",
        {"version": "0.15.0", "confirmation": "确认在线升级"},
        format="json",
    )
    assert response.status_code == 400


def test_get_needs_auth_and_post_needs_csrf_and_recent_auth(client, upgrade_root):
    unauthenticated = APIClient()
    assert unauthenticated.get("/api/v1/system/upgrade/").status_code == 401
    client.credentials()
    assert submit(client).status_code == 403
    csrf = client.get("/api/v1/auth/csrf")
    client.credentials(HTTP_X_CSRFTOKEN=csrf.json()["csrf_token"])
    session = client.session
    session.pop("recent_auth_until", None)
    session.save()
    response = submit(client)
    assert response.status_code == 403
    assert response.json()["code"] == "STEP_UP_REQUIRED"


@pytest.mark.parametrize("target", ["catalog.json", "requests", "results"])
def test_symlink_queue_paths_fail_closed(client, upgrade_root, tmp_path, target):
    path = upgrade_root / target
    if path.is_dir():
        path.rmdir()
    else:
        path.unlink()
    destination = upgrade_root / "elsewhere"
    if target == "catalog.json":
        destination.write_text('{"schema_version":1,"releases":[]}')
    else:
        destination.mkdir()
    path.symlink_to(destination)
    response = client.get("/api/v1/system/upgrade/")
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert submit(client).status_code == 503


def test_invalid_or_oversized_catalog_fails_closed(client, upgrade_root):
    catalog = upgrade_root / "catalog.json"
    catalog.write_text("x" * (256 * 1024 + 1))
    response = client.get("/api/v1/system/upgrade/")
    assert response.status_code == 200 and response.json()["available"] is False
    assert submit(client).status_code == 503


def test_world_writable_catalog_is_unavailable_in_production(client, upgrade_root, settings):
    settings.XRAY_ENV = "production"
    (upgrade_root / "catalog.json").chmod(0o666)
    assert client.get("/api/v1/system/upgrade/").json()["available"] is False


def test_invalid_result_cannot_become_a_job_or_expose_raw_values(client, upgrade_root):
    key = uuid4()
    assert submit(client, key=key).status_code == 202
    (upgrade_root / "results" / f"{key}.json").write_text(
        json.dumps(
            {
                "id": str(key),
                "version": "0.15.0",
                "status": "FAILED",
                "phase": "request password=fixture-secret",
                "updated_at": "2026-11-14T01:00:00Z",
            }
        )
    )
    response = client.get("/api/v1/system/upgrade/")
    assert response.json()["available"] is False
    assert "fixture-secret" not in response.content.decode()
    assert submit(client).status_code == 503


def test_symlink_request_does_not_open_external_file(client, upgrade_root):
    key = uuid4()
    external = upgrade_root / "outside.json"
    external.write_text('{"secret":"fixture-secret"}')
    (upgrade_root / "requests" / f"{key}.json").symlink_to(external)
    assert submit(client, key=key).status_code == 503
    assert external.read_text() == '{"secret":"fixture-secret"}'


def test_queue_lock_serializes_competing_http_requests(client, upgrade_root):
    import fcntl
    import threading
    import time

    lock_path = upgrade_root / "requests" / "queue.lock"
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        from apps.identity.upgrade import _queue_lock

        entered = threading.Event()

        def contender():
            with _queue_lock(upgrade_root / "requests"):
                entered.set()

        thread = threading.Thread(target=contender)
        thread.start()
        time.sleep(0.05)
        assert not entered.is_set()
        fcntl.flock(lock, fcntl.LOCK_UN)
        thread.join(timeout=2)
        assert entered.is_set()


def test_malformed_result_types_fail_closed(client, upgrade_root):
    key = uuid4()
    assert submit(client, key=key).status_code == 202
    (upgrade_root / "results" / f"{key}.json").write_text(
        json.dumps(
            {
                "id": str(key),
                "version": "0.15.0",
                "status": [],
                "phase": {},
                "updated_at": "2026-11-14T01:00:00Z",
            }
        )
    )
    response = client.get("/api/v1/system/upgrade/")
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert submit(client).status_code == 503
