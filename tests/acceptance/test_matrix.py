from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts" / "validate-acceptance.py"


def valid_matrix() -> dict[str, object]:
    return {
        "version": "0.5.0",
        "generated_at": "2026-09-17T08:00:00+08:00",
        "allowed_statuses": [
            "passed",
            "failed",
            "blocked",
            "not-run",
            "risky_not_executed",
        ],
        "items": [
            {
                "id": "local-gates",
                "environment": "local",
                "status": "passed",
                "evidence": [
                    {
                        "kind": "command",
                        "command": "pytest -q",
                        "exit_code": 0,
                        "artifact": "artifacts/acceptance/0.5.0/pytest.txt",
                        "timestamp": "2026-09-17T08:00:00+08:00",
                    }
                ],
                "commit": "0123456789abcdef0123456789abcdef01234567",
                "provider": None,
                "region": None,
                "cost": None,
                "residual_resources": [],
            }
        ],
    }


def run_validator(
    tmp_path: Path,
    matrix: dict[str, object],
    *,
    version: str = "0.5.0",
) -> subprocess.CompletedProcess[str]:
    matrix_path = tmp_path / "matrix.json"
    version_path = tmp_path / "VERSION"
    matrix_path.write_text(json.dumps(matrix), encoding="utf-8")
    version_path.write_text(f"{version}\n", encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--matrix",
            str(matrix_path),
            "--version-file",
            str(version_path),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


def real_cloud_evidence() -> dict[str, object]:
    return {
        "kind": "real_cloud_operation",
        "authorization_ref": "approval-2026-09-17-aws-001",
        "operation_id": "11111111-1111-4111-8111-111111111111",
        "provider_request_id": "req-redacted-8fd2",
        "resource_ref": "instance-redacted-42a1",
        "timestamp": "2026-09-17T08:00:00+08:00",
        "region": "ap-east-1",
        "probe_results": [
            {"protocol": "vless-reality", "expect_accept": True, "result": "accepted"}
        ],
        "artifact": "artifacts/acceptance/0.5.0/aws-real-operation.json",
    }


def real_cloud_row() -> dict[str, object]:
    row = deepcopy(valid_matrix()["items"][0])
    assert isinstance(row, dict)
    row.update(
        {
            "id": "aws-real-cloud",
            "environment": "real_cloud",
            "provider": "aws-lightsail",
            "region": "ap-east-1",
            "evidence": [real_cloud_evidence()],
        }
    )
    return row


def production_row() -> dict[str, object]:
    row = deepcopy(valid_matrix()["items"][0])
    assert isinstance(row, dict)
    row.update(
        {
            "id": "production-release",
            "environment": "production",
            "evidence": [
                {
                    "kind": "production_release",
                    "server_ref": "server-redacted-72d9",
                    "tls_evidence": "artifacts/acceptance/0.5.0/tls.json",
                    "image_digests": {
                        "backend": "sha256:" + "1" * 64,
                        "frontend": "sha256:" + "2" * 64,
                        "backup_tools": "sha256:" + "3" * 64,
                    },
                    "restore_evidence": "artifacts/acceptance/0.5.0/restore-receipt.json",
                    "timestamp": "2026-09-17T08:00:00+08:00",
                }
            ],
        }
    )
    return row


def test_valid_local_matrix_passes(tmp_path: Path) -> None:
    result = run_validator(tmp_path, valid_matrix())

    assert result.returncode == 0, result.stderr
    assert "acceptance matrix valid" in result.stdout


@pytest.mark.parametrize("status", ["complete", "success", "skipped", "PASS"])
def test_unknown_status_is_rejected(tmp_path: Path, status: str) -> None:
    matrix = valid_matrix()
    matrix["items"][0]["status"] = status

    result = run_validator(tmp_path, matrix)

    assert result.returncode != 0
    assert "status" in result.stderr


def test_passed_without_evidence_is_rejected(tmp_path: Path) -> None:
    matrix = valid_matrix()
    matrix["items"][0]["evidence"] = []

    result = run_validator(tmp_path, matrix)

    assert result.returncode != 0
    assert "passed requires evidence" in result.stderr


def test_matrix_version_must_match_version_file(tmp_path: Path) -> None:
    result = run_validator(tmp_path, valid_matrix(), version="0.6.0")

    assert result.returncode != 0
    assert "does not match VERSION" in result.stderr


def test_duplicate_item_id_is_rejected(tmp_path: Path) -> None:
    matrix = valid_matrix()
    matrix["items"].append(deepcopy(matrix["items"][0]))

    result = run_validator(tmp_path, matrix)

    assert result.returncode != 0
    assert "duplicate item id" in result.stderr


@pytest.mark.parametrize("name", ["fake-report.json", "stub-output.json", "mock-cloud.txt"])
def test_real_cloud_cannot_use_fake_evidence(tmp_path: Path, name: str) -> None:
    matrix = valid_matrix()
    row = real_cloud_row()
    row["evidence"] = [name]
    matrix["items"] = [row]

    result = run_validator(tmp_path, matrix)

    assert result.returncode != 0
    assert "structured real-cloud evidence" in result.stderr


@pytest.mark.parametrize(
    "missing",
    [
        "authorization_ref",
        "operation_id",
        "provider_request_id",
        "resource_ref",
        "timestamp",
        "region",
        "probe_results",
    ],
)
def test_real_cloud_pass_requires_complete_external_evidence(
    tmp_path: Path,
    missing: str,
) -> None:
    matrix = valid_matrix()
    row = real_cloud_row()
    evidence = real_cloud_evidence()
    del evidence[missing]
    row["evidence"] = [evidence]
    matrix["items"] = [row]

    result = run_validator(tmp_path, matrix)

    assert result.returncode != 0
    assert missing in result.stderr


def test_real_cloud_pass_accepts_complete_external_evidence(tmp_path: Path) -> None:
    matrix = valid_matrix()
    matrix["items"] = [real_cloud_row()]

    result = run_validator(tmp_path, matrix)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "missing",
    ["server_ref", "tls_evidence", "image_digests", "restore_evidence", "timestamp"],
)
def test_production_pass_requires_release_and_restore_evidence(
    tmp_path: Path,
    missing: str,
) -> None:
    matrix = valid_matrix()
    row = production_row()
    evidence = row["evidence"][0]
    del evidence[missing]
    matrix["items"] = [row]

    result = run_validator(tmp_path, matrix)

    assert result.returncode != 0
    assert missing in result.stderr


def test_production_pass_accepts_complete_release_evidence(tmp_path: Path) -> None:
    matrix = valid_matrix()
    matrix["items"] = [production_row()]

    result = run_validator(tmp_path, matrix)

    assert result.returncode == 0, result.stderr
