from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SCRIPT = ROOT / "scripts" / "package-installer-release.sh"


def test_installer_release_package_contains_only_publishable_assets(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    env = {**os.environ, "XRAY_RELEASE_DIST_DIR": str(dist), "XRAY_RELEASE_TAG": "v0.14.6"}
    result = subprocess.run(
        ["bash", str(PACKAGE_SCRIPT), "0.14.6"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout

    archive = dist / "xray-installer-0.14.6.tar.gz"
    manifest = dist / "xray-installer-0.14.6-manifest.json"
    checksums = dist / "SHA256SUMS"
    assert archive.is_file()
    assert manifest.is_file()
    assert checksums.is_file()

    with tarfile.open(archive, "r:gz") as bundle:
        names = set(bundle.getnames())
    assert "xray-installer-0.14.6/installer/one-click.sh" in names
    assert "xray-installer-0.14.6/installer/manifest.json" in names
    assert not any(".env" in name or "archive/" in name for name in names)

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["version"] == "0.14.6"
    assert payload["tag"] == "v0.14.6"
    assert payload["commit"]

    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert f"{expected}  {archive.name}" in checksums.read_text(encoding="utf-8")
