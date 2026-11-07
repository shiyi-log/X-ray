from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
TRUSTED_LABELS = ["self-hosted", "Linux", "X64", "xray-trusted-2x4"]
CI_RUNNER_EXPRESSION = (
    "${{ github.event_name == 'push' && github.ref == 'refs/heads/main' && "
    'fromJSON(\'["self-hosted","Linux","X64","xray-trusted-2x4"]\') || '
    "'ubuntu-24.04' }}"
)
RELEASE_JOB_EXPRESSION = (
    "${{ github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main' }}"
)


def _job(workflow: str, job: str) -> dict:
    document = yaml.load(
        (ROOT / ".github/workflows" / workflow).read_text(), Loader=yaml.BaseLoader
    )
    return document["jobs"][job]


def _render(value: str, **context) -> str:
    github_values = {
        "sha": context["sha"],
        "run_id": context["run_id"],
        "run_attempt": context["run_attempt"],
        "workspace": context["workspace"],
    }
    return re.sub(
        r"\$\{\{\s*github\.(sha|run_id|run_attempt|workspace)\s*\}\}",
        lambda match: github_values[match[1]],
        value,
    )


@pytest.mark.parametrize(
    ("event", "ref", "expected"),
    [
        ("push", "refs/heads/main", TRUSTED_LABELS),
        ("push", "refs/heads/codex/xray-manager", "ubuntu-24.04"),
        ("pull_request", "refs/pull/12/merge", "ubuntu-24.04"),
        ("pull_request", "refs/heads/main", "ubuntu-24.04"),
    ],
)
def test_ci_routes_only_main_push_to_the_trusted_runner(event, ref, expected):
    actual = " ".join(_job("ci.yml", "verify")["runs-on"].split())
    assert actual == CI_RUNNER_EXPRESSION
    routed_runner = (
        TRUSTED_LABELS
        if event == "push" and ref == "refs/heads/main"
        else "ubuntu-24.04"
    )
    assert routed_runner == expected


@pytest.mark.parametrize(
    ("event", "ref", "allowed"),
    [
        ("push", "refs/tags/v0.1.0", False),
        ("workflow_dispatch", "refs/heads/main", True),
        ("workflow_dispatch", "refs/heads/feature", False),
        ("pull_request", "refs/pull/12/merge", False),
        ("push", "refs/heads/main", False),
    ],
)
def test_release_job_accepts_only_dispatch_from_main(event, ref, allowed):
    document = yaml.load(
        (ROOT / ".github/workflows/release.yml").read_text(), Loader=yaml.BaseLoader
    )
    job = _job("release.yml", "release")
    assert set(document["on"]) == {"workflow_dispatch"}
    assert document["on"]["workflow_dispatch"]["inputs"]["tag"]["required"] == "true"
    assert job["runs-on"] == TRUSTED_LABELS
    assert " ".join(job.get("if", "").split()) == RELEASE_JOB_EXPRESSION
    eligible = event == "workflow_dispatch" and ref == "refs/heads/main"
    assert eligible is allowed


def test_checkouts_do_not_persist_job_credentials():
    for workflow, name in (("ci.yml", "verify"), ("release.yml", "release")):
        steps = _job(workflow, name)["steps"]
        checkout = next(
            step
            for step in steps
            if step.get("uses", "").startswith("actions/checkout@")
        )
        assert checkout["with"].get("persist-credentials") == "false"


def test_ci_images_and_uploaded_evidence_are_unique_to_each_run_attempt():
    job = _job("ci.yml", "verify")
    contexts = [
        {"sha": "a" * 40, "run_id": "101", "run_attempt": "1", "workspace": "/repo"},
        {"sha": "a" * 40, "run_id": "101", "run_attempt": "2", "workspace": "/repo"},
        {"sha": "b" * 40, "run_id": "102", "run_attempt": "1", "workspace": "/repo"},
    ]
    for key in (
        "XRAY_BACKEND_TEST_IMAGE",
        "XRAY_FRONTEND_TEST_IMAGE",
        "XRAY_BACKUP_TEST_IMAGE",
        "XRAY_ACCEPTANCE_ARTIFACT_DIR",
    ):
        values = [_render(job["env"].get(key, ""), **context) for context in contexts]
        assert len(set(values)) == 3, f"{key} reuses a previous run's output"
    assert job["env"]["XRAY_ACCEPTANCE_ARTIFACT_DIR"].startswith(
        "${{ github.workspace }}/"
    )
    upload = next(
        step
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["with"]["path"] == "${{ env.XRAY_ACCEPTANCE_ARTIFACT_DIR }}/"
    assert upload["with"]["name"].endswith("-${{ github.run_attempt }}")


def test_ci_cleanup_removes_only_its_images_and_temporary_auth_state(tmp_path):
    steps = _job("ci.yml", "verify")["steps"]
    prepare = next(
        (step for step in steps if step.get("id") == "acceptance-paths"), None
    )
    cleanup = next((step for step in steps if step.get("id") == "cleanup-run"), None)
    assert prepare is not None, "CI must prepare an auth path outside uploaded evidence"
    assert cleanup is not None and cleanup.get("if") == "always()"
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    github_env = tmp_path / "github-env"
    tools = tmp_path / "bin"
    tools.mkdir()
    images = tmp_path / "images.json"
    images.write_text(
        json.dumps(["backend:run", "frontend:run", "backup:run", "shared:base"])
    )
    docker = tools / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "assert sys.argv[1:4] == ['image', 'rm', '--force']\n"
        "path = Path(os.environ['TEST_IMAGES'])\n"
        "path.write_text(json.dumps([image for image in json.loads(path.read_text()) "
        "if image not in sys.argv[4:]]))\n"
    )
    docker.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_ENV": str(github_env),
        "TEST_IMAGES": str(images),
        "XRAY_BACKEND_TEST_IMAGE": "backend:run",
        "XRAY_FRONTEND_TEST_IMAGE": "frontend:run",
        "XRAY_BACKUP_TEST_IMAGE": "backup:run",
    }
    subprocess.run(
        ["bash", "-euo", "pipefail", "-c", prepare["run"]], env=environment, check=True
    )
    key, value = github_env.read_text().strip().split("=", 1)
    assert key == "XRAY_PLAYWRIGHT_AUTH_STATE"
    auth_state = Path(value)
    assert auth_state.is_relative_to(runner_temp)
    auth_state.write_text('{"cookies": []}')
    environment[key] = value
    subprocess.run(
        ["bash", "-euo", "pipefail", "-c", cleanup["run"]], env=environment, check=True
    )
    assert not auth_state.exists()
    assert json.loads(images.read_text()) == ["shared:base"]


@pytest.mark.parametrize("trusted", [True, False])
def test_release_tag_must_point_to_a_commit_reachable_from_main(tmp_path, trusted):
    steps = _job("release.yml", "release")["steps"]
    verification = next(step for step in steps if step.get("name") == "校验发布标签")
    checkout_release = next(
        step for step in steps if step.get("name") == "检出已验证的发布提交"
    )
    initial_checkout = next(
        step
        for step in steps
        if step.get("uses", "").startswith("actions/checkout@")
    )
    assert "ref" not in initial_checkout["with"]
    assert steps.index(verification) < steps.index(checkout_release)
    git = [
        "git",
        "-c",
        "user.name=Runner test",
        "-c",
        "user.email=runner@example.invalid",
    ]
    subprocess.run([*git, "init", "--quiet"], cwd=tmp_path, check=True)
    (tmp_path / "VERSION").write_text("0.1.0\n")
    subprocess.run([*git, "add", "VERSION"], cwd=tmp_path, check=True)
    subprocess.run(
        [*git, "commit", "--quiet", "-m", "trusted release source"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        [*git, "update-ref", "refs/remotes/origin/main", "HEAD"],
        cwd=tmp_path,
        check=True,
    )
    if not trusted:
        (tmp_path / "unreviewed.txt").write_text("not reachable from main\n")
        subprocess.run([*git, "add", "unreviewed.txt"], cwd=tmp_path, check=True)
        subprocess.run(
            [*git, "commit", "--quiet", "-m", "unreviewed commit"],
            cwd=tmp_path,
            check=True,
        )
    subprocess.run(
        [*git, "tag", "-a", "v0.1.0", "-m", "test release"], cwd=tmp_path, check=True
    )
    github_env = tmp_path / "github-env"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", verification["run"]],
        cwd=tmp_path,
        env={**os.environ, "RELEASE_TAG": "v0.1.0", "GITHUB_ENV": str(github_env)},
        capture_output=True,
    )
    assert (result.returncode == 0) is trusted
    if trusted:
        expected_commit = subprocess.run(
            ["git", "rev-parse", "v0.1.0^{commit}"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert github_env.read_text() == f"RELEASE_COMMIT={expected_commit}\n"
