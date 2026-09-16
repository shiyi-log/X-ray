#!/usr/bin/env python3
"""Validate the auditable acceptance ledger without contacting external systems."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID


ALLOWED_STATUSES = (
    "passed",
    "failed",
    "blocked",
    "not-run",
    "risky_not_executed",
)
REQUIRED_ROW_FIELDS = (
    "id",
    "environment",
    "status",
    "evidence",
    "commit",
    "provider",
    "region",
    "cost",
    "residual_resources",
)
FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SIMULATED_MARKER = re.compile(r"(^|[^a-z])(fake|mock|stub)([^a-z]|$)", re.IGNORECASE)


class MatrixValidationError(ValueError):
    """Raised when an acceptance claim is incomplete or misleading."""


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MatrixValidationError(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise MatrixValidationError(f"{label} must be an array")
    return value


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MatrixValidationError(f"{label} must be a non-empty string")
    return value.strip()


def _require_timestamp(value: Any, label: str) -> None:
    text = _require_text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MatrixValidationError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise MatrixValidationError(f"{label} must include a timezone")


def _require_uuid(value: Any, label: str) -> None:
    text = _require_text(value, label)
    try:
        parsed = UUID(text)
    except ValueError as exc:
        raise MatrixValidationError(f"{label} must be a complete UUID") from exc
    if parsed.int == 0:
        raise MatrixValidationError(f"{label} must not be the nil UUID")


def _find_evidence(
    evidence: list[Any],
    *,
    kind: str,
    label: str,
) -> dict[str, Any]:
    matching = [item for item in evidence if isinstance(item, dict) and item.get("kind") == kind]
    if not matching:
        raise MatrixValidationError(f"{label} requires structured {kind.replace('_', '-')} evidence")
    return matching[0]


def _validate_real_cloud(row: dict[str, Any], label: str) -> None:
    evidence = _require_list(row["evidence"], f"{label}.evidence")
    serialized = json.dumps(evidence, ensure_ascii=True)
    if SIMULATED_MARKER.search(serialized):
        raise MatrixValidationError(
            f"{label} requires structured real-cloud evidence; Fake/Mock/Stub evidence is invalid"
        )
    item = _find_evidence(
        evidence,
        kind="real_cloud_operation",
        label=f"{label} passed real cloud",
    )
    for field in (
        "authorization_ref",
        "provider_request_id",
        "resource_ref",
        "region",
    ):
        _require_text(item.get(field), f"{label}.evidence.{field}")
    _require_uuid(item.get("operation_id"), f"{label}.evidence.operation_id")
    _require_timestamp(item.get("timestamp"), f"{label}.evidence.timestamp")
    probes = _require_list(item.get("probe_results"), f"{label}.evidence.probe_results")
    if not probes:
        raise MatrixValidationError(f"{label}.evidence.probe_results must not be empty")
    provider = _require_text(row.get("provider"), f"{label}.provider")
    region = _require_text(row.get("region"), f"{label}.region")
    if item["region"] != region:
        raise MatrixValidationError(f"{label}.evidence.region must match row region")
    if provider not in {"aws-lightsail", "aliyun-swas"}:
        raise MatrixValidationError(f"{label}.provider is not a supported real-cloud provider")
    if "redacted" not in item["resource_ref"].lower():
        raise MatrixValidationError(f"{label}.evidence.resource_ref must be redacted")


def _validate_production(row: dict[str, Any], label: str) -> None:
    evidence = _require_list(row["evidence"], f"{label}.evidence")
    item = _find_evidence(
        evidence,
        kind="production_release",
        label=f"{label} passed production",
    )
    for field in ("server_ref", "tls_evidence", "restore_evidence"):
        _require_text(item.get(field), f"{label}.evidence.{field}")
    _require_timestamp(item.get("timestamp"), f"{label}.evidence.timestamp")
    if "redacted" not in item["server_ref"].lower():
        raise MatrixValidationError(f"{label}.evidence.server_ref must be redacted")
    digests = _require_mapping(item.get("image_digests"), f"{label}.evidence.image_digests")
    for image in ("backend", "frontend", "backup_tools"):
        value = digests.get(image)
        if not isinstance(value, str) or not IMAGE_DIGEST.fullmatch(value):
            raise MatrixValidationError(
                f"{label}.evidence.image_digests.{image} must be an immutable sha256 digest"
            )


def validate_row(row: Any, *, index: int) -> str:
    item = _require_mapping(row, f"items[{index}]")
    label = f"items[{index}]"
    missing = [field for field in REQUIRED_ROW_FIELDS if field not in item]
    if missing:
        raise MatrixValidationError(f"{label} missing fields: {', '.join(missing)}")

    item_id = _require_text(item["id"], f"{label}.id")
    label = f"item {item_id}"
    _require_text(item["environment"], f"{label}.environment")
    status = _require_text(item["status"], f"{label}.status")
    if status not in ALLOWED_STATUSES:
        raise MatrixValidationError(f"{label}.status {status!r} is not allowed")
    evidence = _require_list(item["evidence"], f"{label}.evidence")
    _require_list(item["residual_resources"], f"{label}.residual_resources")

    if status == "passed":
        if not evidence:
            raise MatrixValidationError(f"{label}: passed requires evidence")
        commit = _require_text(item["commit"], f"{label}.commit")
        if not FULL_COMMIT.fullmatch(commit):
            raise MatrixValidationError(f"{label}.commit must be a complete 40-character SHA")
        if item["environment"] == "real_cloud":
            _validate_real_cloud(item, label)
        if item["environment"] == "production":
            _validate_production(item, label)

    return item_id


def validate_matrix(document: Any, *, expected_version: str) -> None:
    matrix = _require_mapping(document, "matrix")
    version = _require_text(matrix.get("version"), "matrix.version")
    if version != expected_version:
        raise MatrixValidationError(
            f"matrix version {version!r} does not match VERSION {expected_version!r}"
        )
    _require_text(matrix.get("generated_at"), "matrix.generated_at")
    statuses = _require_list(matrix.get("allowed_statuses"), "matrix.allowed_statuses")
    if len(statuses) != len(set(statuses)) or set(statuses) != set(ALLOWED_STATUSES):
        raise MatrixValidationError(
            "matrix.allowed_statuses must contain only: " + ", ".join(ALLOWED_STATUSES)
        )
    items = _require_list(matrix.get("items"), "matrix.items")
    if not items:
        raise MatrixValidationError("matrix.items must not be empty")

    seen: set[str] = set()
    for index, row in enumerate(items):
        item_id = validate_row(row, index=index)
        if item_id in seen:
            raise MatrixValidationError(f"duplicate item id: {item_id}")
        seen.add(item_id)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=Path("tests/acceptance/matrix.json"))
    parser.add_argument("--version-file", type=Path, default=Path("VERSION"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        expected_version = args.version_file.read_text(encoding="utf-8").strip()
        document = json.loads(args.matrix.read_text(encoding="utf-8"))
        validate_matrix(document, expected_version=expected_version)
    except (OSError, json.JSONDecodeError, MatrixValidationError) as exc:
        print(f"acceptance matrix invalid: {exc}", file=sys.stderr)
        return 1
    print(f"acceptance matrix valid: {args.matrix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
