from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("dockerfile", "allowed_copy_roots"),
    [
        ("deploy/docker/backend.Dockerfile", ("backend/", "installer/", "deploy/scripts/")),
        ("deploy/docker/frontend.Dockerfile", ("frontend/", "deploy/nginx/")),
    ],
)
def test_dockerfiles_copy_only_explicit_application_roots(dockerfile, allowed_copy_roots):
    lines = (ROOT / dockerfile).read_text(encoding="utf-8").splitlines()
    copy_lines = [line.strip() for line in lines if line.strip().startswith("COPY ")]
    assert copy_lines
    for line in copy_lines:
        if "--from=" in line:
            continue
        assert any(root in line for root in allowed_copy_roots), line
        assert "COPY ." not in line


@pytest.mark.parametrize(
    ("environment_key", "expected_user", "application_root"),
    [
        ("XRAY_BACKEND_TEST_IMAGE", "10001:10001", "/app"),
        ("XRAY_FRONTEND_TEST_IMAGE", "10001:0", "/usr/share/nginx/html"),
    ],
)
def test_built_runtime_image_is_non_root_and_contains_no_forbidden_paths(
    environment_key, expected_user, application_root
):
    image = os.getenv(environment_key)
    if not image:
        pytest.skip(f"{environment_key} is required for the built-image gate")
    user = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Config.User}}", image],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert user == expected_user
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/bin/sh",
            image,
            "-c",
            (
                f"test ! -e {application_root}/archive && "
                f"test ! -e {application_root}/runtime && "
                f"! find {application_root} -name '.env' -o -name '.env.*' | grep -q ."
            ),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
