"""Administrator upgrade requests; the application never executes host commands."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone

from apps.audit.services import AuditService
from common.admin_api import admin_endpoint, json_payload
from common.errors import DomainError

from .services import require_recent_step_up

_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_TERMINAL = {"SUCCEEDED", "FAILED"}
_STATUSES = _TERMINAL | {"QUEUED", "RUNNING"}
_PHASES = {
    "QUEUED",
    "PREFLIGHT",
    "BACKUP",
    "DRAIN",
    "MIGRATE",
    "DEPLOY",
    "VERIFY",
    "COMPLETE",
    "FAILED",
    "VALIDATING",
    "RELEASING",
    "ROLLBACK_REQUIRED",
}
_ERRORS = {
    "UPGRADE_FAILED",
    "PREFLIGHT_FAILED",
    "BACKUP_FAILED",
    "DRAIN_FAILED",
    "MIGRATION_FAILED",
    "DEPLOY_FAILED",
    "VERIFICATION_FAILED",
    "INVALID_RELEASE",
}
_LIMIT = 256 * 1024


def _unavailable():
    return DomainError(
        "UPGRADE_UNAVAILABLE", "在线升级尚未就绪，请检查主机升级服务", status_code=503
    )


def _version(value):
    if not isinstance(value, str) or not _VERSION.fullmatch(value):
        raise ValueError("version must use MAJOR.MINOR.PATCH")
    return tuple(int(part) for part in value.split("."))


def _current_version():
    return (settings.BASE_DIR.parent / "VERSION").read_text(encoding="utf-8").strip()


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        raise _unavailable()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _unavailable() from exc
    if parsed.tzinfo is None:
        raise _unavailable()
    return value


def _directory(path):
    if path.is_symlink() or not path.is_dir() or path.resolve() != path.absolute():
        raise _unavailable()
    return path


def _read_json(path, *, root_owned=False):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _LIMIT:
                raise _unavailable()
            if (
                root_owned
                and settings.XRAY_ENV == "production"
                and (metadata.st_uid != 0 or metadata.st_mode & 0o022)
            ):
                raise _unavailable()
            raw = handle.read(_LIMIT + 1)
            if len(raw) > _LIMIT:
                raise _unavailable()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise _unavailable()
        return value
    except (OSError, ValueError, TypeError) as exc:
        raise _unavailable() from exc


def _configuration():
    raw = getattr(settings, "XRAY_UPGRADE_ROOT", os.getenv("XRAY_UPGRADE_ROOT", ""))
    if not raw or not Path(raw).is_absolute():
        raise _unavailable()
    root = _directory(Path(raw))
    requests = _directory(root / "requests")
    results = _directory(root / "results")
    catalog = _read_json(root / "catalog.json", root_owned=True)
    if (
        catalog.get("schema_version") != 1
        or not isinstance(catalog.get("releases"), list)
        or len(catalog["releases"]) > 100
    ):
        raise _unavailable()
    candidates = []
    seen = set()
    current = _version(_current_version())
    for entry in catalog["releases"]:
        if not isinstance(entry, dict):
            raise _unavailable()
        try:
            parsed = _version(entry.get("version"))
        except ValueError as exc:
            raise _unavailable() from exc
        version = entry["version"]
        if (
            version in seen
            or not isinstance(entry.get("notes", ""), str)
            or len(entry.get("notes", "")) > 10000
        ):
            raise _unavailable()
        seen.add(version)
        if parsed >= current:
            candidates.append(
                {
                    "version": version,
                    "published_at": _timestamp(entry.get("published_at")),
                    "notes": entry.get("notes", ""),
                }
            )
    candidates.sort(key=lambda item: _version(item["version"]), reverse=True)
    return requests, results, candidates


def _request_record(path):
    record = _read_json(path)
    try:
        identifier = str(UUID(record.get("id", "")))
        _version(record.get("version"))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _unavailable() from exc
    if record.get("schema_version") != 1 or path.name != identifier + ".json":
        raise _unavailable()
    _timestamp(record.get("created_at"))
    return record


def _job(record, results):
    job = {
        "id": record["id"],
        "version": record["version"],
        "status": "QUEUED",
        "phase": "QUEUED",
        "error_code": None,
        "created_at": record["created_at"],
        "updated_at": record["created_at"],
    }
    path = results / (record["id"] + ".json")
    if path.exists() or path.is_symlink():
        result = _read_json(path, root_owned=True)
        if (
            result.get("id") != record["id"]
            or result.get("version") != record["version"]
            or not isinstance(result.get("status"), str)
            or not isinstance(result.get("phase"), str)
            or result.get("status") not in _STATUSES
            or result.get("phase") not in _PHASES
        ):
            raise _unavailable()
        job.update(
            status=result["status"],
            phase=result["phase"],
            updated_at=_timestamp(result.get("updated_at")),
        )
        if result.get("error_code"):
            error_code = result["error_code"]
            job["error_code"] = (
                error_code
                if isinstance(error_code, str) and error_code in _ERRORS
                else "UPGRADE_FAILED"
            )
    return job


def _jobs(requests, results):
    files = list(requests.glob("*.json"))
    if len(files) > 1000:
        raise _unavailable()
    jobs = [_job(_request_record(path), results) for path in files]
    return sorted(jobs, key=lambda item: (item["created_at"], item["id"]), reverse=True)


@contextmanager
def _queue_lock(requests):
    try:
        fd = os.open(requests / "queue.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o640)
        with os.fdopen(fd, "a") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise _unavailable()
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield
    except OSError as exc:
        raise _unavailable() from exc


def _write_request(requests, record):
    temporary = requests / (".incoming-" + str(uuid4()))
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o640)
            handle.write((json.dumps(record, separators=(",", ":")) + "\n").encode())
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, requests / (record["id"] + ".json"), follow_symlinks=False)
        directory_fd = os.open(requests, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise _unavailable() from exc
    finally:
        temporary.unlink(missing_ok=True)


@require_recent_step_up
def _submit(request):
    payload = json_payload(request)
    if set(payload) != {"version", "confirmation"} or payload.get("confirmation") != "确认在线升级":
        raise ValueError("version and explicit upgrade confirmation are required")
    selected = payload["version"]
    _version(selected)
    try:
        identifier = UUID(request.headers.get("Idempotency-Key", ""))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("a UUID Idempotency-Key is required") from exc
    if identifier.int == 0:
        raise ValueError("a nonzero UUID Idempotency-Key is required")
    requests, results, candidates = _configuration()
    with _queue_lock(requests):
        existing = requests / (str(identifier) + ".json")
        if existing.exists() or existing.is_symlink():
            record = _request_record(existing)
            if record["version"] != selected:
                raise DomainError(
                    "IDEMPOTENCY_CONFLICT", "幂等键已用于其他升级请求", status_code=409
                )
            return JsonResponse(_job(record, results), status=202)
        if selected not in {item["version"] for item in candidates}:
            raise DomainError(
                "UPGRADE_VERSION_UNAVAILABLE", "请选择已登记且不低于当前的版本", status_code=409
            )
        if any(job["status"] not in _TERMINAL for job in _jobs(requests, results)):
            raise DomainError("UPGRADE_IN_PROGRESS", "已有升级正在执行", status_code=409)
        record = {
            "schema_version": 1,
            "id": str(identifier),
            "version": selected,
            "created_at": timezone.now().isoformat(),
            "actor_id": str(request.xray_admin.pk),
        }
        with transaction.atomic():
            AuditService.append(
                action="system.upgrade.submit",
                target_type="system_upgrade",
                target_id=identifier,
                result="QUEUED",
                actor=request.xray_admin,
                metadata={"version": selected},
            )
            _write_request(requests, record)
        return JsonResponse(_job(record, results), status=202)


@admin_endpoint("GET", "POST")
def upgrade(request):
    if request.method == "POST":
        return _submit(request)
    body = {
        "current_version": _current_version(),
        "available": False,
        "reason": "在线升级尚未就绪，请检查主机升级服务",
        "candidates": [],
        "jobs": [],
    }
    try:
        requests, results, candidates = _configuration()
        body.update(
            available=True, reason=None, candidates=candidates, jobs=_jobs(requests, results)[:20]
        )
    except (DomainError, OSError, ValueError):
        pass
    return JsonResponse(body)
