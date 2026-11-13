from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_backend_image_contains_the_release_version():
    image = os.getenv("XRAY_BACKEND_TEST_IMAGE")
    if not image:
        pytest.skip("backend image required for version gate")
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--read-only", image,
         "python", "-c", "from pathlib import Path; print(Path('/app/VERSION').read_text().strip())"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (ROOT / "VERSION").read_text().strip()


@pytest.mark.parametrize(
    ("command", "output_prefix"),
    [("gunicorn", "gunicorn (version "), ("celery", "5.")],
)
def test_backend_console_scripts_execute_from_the_runtime_environment(command, output_prefix):
    image = os.getenv("XRAY_BACKEND_TEST_IMAGE")
    if not image:
        pytest.skip("XRAY_BACKEND_TEST_IMAGE is required for the console-script gate")
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--read-only", image, command, "--version"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(output_prefix), result.stdout


@pytest.mark.parametrize(
    ("dockerfile", "allowed_copy_roots"),
    [
        ("deploy/docker/backend.Dockerfile", ("backend/", "installer/", "deploy/scripts/", "VERSION")),
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


def test_frontend_dockerfile_copies_workspace_packages_before_install():
    frontend_dockerfile = ROOT / "deploy/docker/frontend.Dockerfile"
    lines = frontend_dockerfile.read_text(encoding="utf-8").splitlines()
    install_index = lines.index("RUN pnpm install --frozen-lockfile")
    copied_workspace_roots = {
        line.strip()
        for line in lines[:install_index]
        if line.strip().startswith("COPY frontend/")
    }

    assert "COPY frontend/internal/ ./internal/" in copied_workspace_roots
    assert "COPY frontend/packages/ ./packages/" in copied_workspace_roots


def test_dockerignore_excludes_nested_dependencies_and_virtualenvs():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert "**/node_modules/" in dockerignore
    assert "**/.venv/" in dockerignore
    assert "artifacts/" in dockerignore
    assert ".local-tools/" in dockerignore


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
