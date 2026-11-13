#!/usr/bin/env python3
"""Run only locally prepared X-ray releases; the web process has no Docker access."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$")
REQUEST_KEYS = {"schema_version", "id", "version", "created_at", "actor_id"}
REQUEST_TTL_SECONDS = 90 * 60


class Rejected(Exception):
    def __init__(self, code: str):
        self.code = code


def version_tuple(value: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise Rejected("REQUEST_INVALID")
    return tuple(int(item) for item in value.split("."))


def read_regular(path: Path, *, limit=65536) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > limit
            or metadata.st_nlink != 1
        ):
            raise Rejected("REQUEST_INVALID")
        value = os.read(fd, limit + 1)
        if len(value) > limit:
            raise Rejected("REQUEST_INVALID")
        return value
    finally:
        os.close(fd)


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    temporary = path.with_name("." + path.name + "." + str(uuid4()))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


class Runner:
    def __init__(
        self, root: Path, config: Path, current_version: Path, *, trusted_uid=0
    ):
        self.root = root
        self.config = config
        self.current_version = current_version
        self.trusted_uid = trusted_uid

    def _trusted(self, path: Path, *, directory=False) -> None:
        info = path.lstat()
        valid_type = (
            stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        )
        if not valid_type or info.st_uid != self.trusted_uid or info.st_mode & 0o022:
            raise Rejected("RELEASE_UNTRUSTED")
        if not directory and info.st_nlink != 1:
            raise Rejected("RELEASE_UNTRUSTED")

    def _private_dir(self, name: str) -> Path:
        path = self.root / name
        path.mkdir(mode=0o700, exist_ok=True)
        self._trusted(path, directory=True)
        os.chmod(path, 0o700)
        return path

    def _result(self, job: dict, status: str, phase: str, error_code="") -> None:
        now = datetime.now(UTC).isoformat()
        result = {
            "id": job["id"],
            "version": job.get("version", ""),
            "status": status,
            "phase": phase,
            "error_code": error_code,
            "created_at": job.get("created_at", now),
            "updated_at": now,
        }
        atomic_write(
            self.root / "results" / (job["id"] + ".json"),
            (json.dumps(result, sort_keys=True) + "\n").encode(),
            0o644,
        )

    def _request(self, path: Path) -> dict:
        lock_fd = os.open(
            path.parent / "queue.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o640
        )
        with os.fdopen(lock_fd, "a") as lock:
            if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
                raise Rejected("REQUEST_INVALID")
            fcntl.flock(lock, fcntl.LOCK_EX)
            value = json.loads(read_regular(path, limit=16384))
        if (
            not isinstance(value, dict)
            or set(value) != REQUEST_KEYS
            or value["schema_version"] != 1
        ):
            raise Rejected("REQUEST_INVALID")
        if (
            str(UUID(value["id"])) != path.stem
            or not isinstance(value["actor_id"], str)
            or not re.fullmatch(r"[1-9][0-9]{0,18}", value["actor_id"])
        ):
            raise Rejected("REQUEST_INVALID")
        version_tuple(value["version"])
        return value

    def _validate_time(self, value: dict) -> None:
        created = datetime.fromisoformat(value["created_at"])
        if created.tzinfo is None:
            raise Rejected("REQUEST_INVALID")
        age = (datetime.now(UTC) - created).total_seconds()
        if age < -60:
            raise Rejected("REQUEST_INVALID")
        if age >= REQUEST_TTL_SECONDS:
            raise Rejected("REQUEST_EXPIRED")

    def _release(self, version: str) -> tuple[Path, dict]:
        self._trusted(self.root / "catalog.json")
        catalog = json.loads(read_regular(self.root / "catalog.json"))
        if not isinstance(catalog, dict) or catalog.get("schema_version") != 1:
            raise Rejected("RELEASE_UNAVAILABLE")
        releases = catalog.get("releases")
        if not isinstance(releases, list) or len(releases) > 100:
            raise Rejected("RELEASE_UNAVAILABLE")
        if not any(
            isinstance(item, dict) and item.get("version") == version
            for item in releases
        ):
            raise Rejected("RELEASE_UNAVAILABLE")
        self._trusted(self.root / "releases", directory=True)
        release = self.root / "releases" / version
        self._trusted(release, directory=True)
        self._trusted(release / "manifest.json")
        manifest = json.loads(read_regular(release / "manifest.json"))
        if (
            not isinstance(manifest, dict)
            or set(manifest)
            != {"schema_version", "version", "backend_image", "frontend_image"}
            or manifest["schema_version"] != 1
            or manifest["version"] != version
            or any(
                not isinstance(manifest[key], str) or not IMAGE.fullmatch(manifest[key])
                for key in ("backend_image", "frontend_image")
            )
        ):
            raise Rejected("RELEASE_UNTRUSTED")
        source = release / "source"
        self._trusted(source, directory=True)
        for directory, folders, files in os.walk(source, followlinks=False):
            for name in folders:
                self._trusted(Path(directory) / name, directory=True)
            for name in files:
                self._trusted(Path(directory) / name)
        if read_regular(source / "VERSION").decode().strip() != version:
            raise Rejected("RELEASE_UNTRUSTED")
        for name in ("deploy/scripts/release.sh", "deploy/compose/production.yml"):
            self._trusted(source / name)
        return source, manifest

    def _execute(self, command: list[str], *, timeout=1200) -> None:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
        if completed.returncode:
            raise Rejected("RELEASE_FAILED")

    def _export_snapshot(self, source: Path, output: Path) -> None:
        export_dir = output.parent / ("export-" + str(uuid4()))
        export_dir.mkdir(mode=0o700)
        os.chown(export_dir, 10001, 10001)
        exported = export_dir / "security.json"
        try:
            self._execute(
                [
                    "docker",
                    "compose",
                    "--env-file",
                    str(self.config),
                    "-f",
                    str(source / "deploy/compose/production.yml"),
                    "run",
                    "--rm",
                    "-v",
                    str(export_dir) + ":/upgrade-export",
                    "admin-api",
                    "python",
                    "/app/backend/manage.py",
                    "export_security_events",
                    "--output",
                    "/upgrade-export/security.json",
                ],
                timeout=120,
            )
            data = read_regular(exported, limit=32 * 1024 * 1024)
            snapshot = json.loads(data)
            if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
                raise Rejected("SECURITY_EXPORT_FAILED")
            atomic_write(output, data, 0o600)
        finally:
            if exported.is_file() and not exported.is_symlink():
                exported.unlink()
            export_dir.rmdir()

    def _write_config(self, content: bytes, values: dict[str, str]) -> None:
        lines = content.decode().splitlines()
        seen = set()
        replaced = []
        for line in lines:
            key = line.split("=", 1)[0]
            if key in values:
                if key in seen:
                    raise Rejected("CONFIG_INVALID")
                replaced.append(key + "=" + values[key])
                seen.add(key)
            else:
                replaced.append(line)
        replaced.extend(
            key + "=" + value for key, value in values.items() if key not in seen
        )
        atomic_write(self.config, ("\n".join(replaced) + "\n").encode(), 0o600)

    def _process(self, path: Path) -> None:
        job = {
            "id": path.stem,
            "version": "",
            "created_at": datetime.now(UTC).isoformat(),
        }
        original = None
        changed = False
        try:
            job = self._request(path)
            self._validate_time(job)
            self._result(job, "RUNNING", "VALIDATING")
            source, manifest = self._release(job["version"])
            self._trusted(self.current_version)
            if version_tuple(job["version"]) < version_tuple(
                read_regular(self.current_version).decode().strip()
            ):
                raise Rejected("DOWNGRADE_FORBIDDEN")
            self._trusted(self.config)
            original = read_regular(self.config)
            history = self._private_dir("history")
            previous = history / (job["id"] + ".env")
            if previous.exists():
                raise Rejected("REQUEST_ALREADY_CLAIMED")
            atomic_write(previous, original, 0o600)
            self._result(job, "RUNNING", "BACKUP")
            snapshot = history / (job["id"] + "-security.json")
            self._export_snapshot(source, snapshot)
            self._write_config(
                original,
                {
                    "XRAY_BACKEND_IMAGE": manifest["backend_image"],
                    "XRAY_FRONTEND_IMAGE": manifest["frontend_image"],
                    "XRAY_SECURITY_LEDGER_SNAPSHOT_FILE": str(snapshot),
                },
            )
            changed = True
            self._result(job, "RUNNING", "RELEASING")
            self._execute(
                [
                    str(source / "deploy/scripts/release.sh"),
                    "--version",
                    job["version"],
                    "--digest",
                    manifest["backend_image"].rsplit("@", 1)[1],
                    "--config",
                    str(self.config),
                    "--compose",
                    str(source / "deploy/compose/production.yml"),
                ]
            )
            atomic_write(self.current_version, (job["version"] + "\n").encode(), 0o644)
            self._result(job, "SUCCEEDED", "COMPLETE")
        except Exception as exc:
            if changed and original is not None:
                atomic_write(self.config, original, 0o600)
            code = exc.code if isinstance(exc, Rejected) else "UPGRADE_FAILED"
            self._result(
                job, "FAILED", "ROLLBACK_REQUIRED" if changed else "VALIDATING", code
            )

    def tick(self) -> int:
        self._trusted(self.root, directory=True)
        self._trusted(self.root / "results", directory=True)
        requests = self.root / "requests"
        if requests.is_symlink() or not requests.is_dir():
            raise Rejected("REQUEST_INVALID")
        lock_fd = os.open(
            self.root / ".runner.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(lock_fd, "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 0
            processed = 0
            for path in sorted(requests.glob("*.json")):
                try:
                    if str(UUID(path.stem)) != path.stem:
                        continue
                except ValueError:
                    continue
                result = self.root / "results" / path.name
                if result.exists():
                    self._trusted(result)
                    state = json.loads(read_regular(result))
                    if state.get("status") == "RUNNING":
                        self._result(
                            state, "FAILED", "ROLLBACK_REQUIRED", "UPGRADE_INTERRUPTED"
                        )
                    continue
                self._process(path)
                processed += 1
                break
            return processed


def main() -> int:
    if os.geteuid() != 0:
        return 1
    try:
        Runner(
            Path("/var/lib/xray/upgrade"),
            Path("/etc/xray/config.env"),
            Path("/opt/xray/VERSION"),
        ).tick()
    except Exception:
        # No request, credentials, exception text, or subprocess output is logged.
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
