from __future__ import annotations

import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "installer" / "one-click.sh"


def test_one_click_uses_pinned_https_download_and_existing_installer():
    content = SCRIPT.read_text()

    assert "--proto '=https'" in content
    assert "--proto-redir '=https'" in content
    assert "--tlsv1.2" in content
    assert "BUNDLE_HASH_MISMATCH" in content
    assert "bash \"$helper_dir/install.sh\" \"$archive\"" in content
    assert "bash \"$helper_dir/verify.sh\"" in content
    assert "releases/latest" not in content
    assert "latest" in content


def test_one_click_supports_interactive_install_and_update():
    content = SCRIPT.read_text()

    assert "全新安装" in content
    assert "更新已有安装" in content
    assert "XRAY_ONE_CLICK_ACTION" in content
    assert "old_binary_present" in content
    assert "SERVICE_RESTART_FAILED" in content
    assert "ref=${XRAY_INSTALLER_REF:-v0.14.0}" in content


def _write_archive(path: Path, marker: str) -> None:
    with zipfile.ZipFile(path, "w") as bundle:
        executable = zipfile.ZipInfo("xray")
        executable.external_attr = 0o100755 << 16
        bundle.writestr(
            executable,
            "#!/bin/sh\n"
            "if [ \"$1\" = version ]; then\n"
            f"  echo 'Xray 26.3.27 {marker}'\n"
            "fi\n",
        )
        bundle.writestr("geoip.dat", b"fixture")
        bundle.writestr("geosite.dat", b"fixture")


def test_one_click_install_then_update_preserves_config_and_generation(tmp_path: Path):
    if os.uname().sysname != "Linux":
        pytest.skip("one-click runtime integration requires a disposable Linux host")
    archive = tmp_path / "fixture-xray.zip"
    _write_archive(archive, "initial")
    platform = "linux-amd64" if os.uname().machine in {"x86_64", "amd64"} else "linux-arm64"
    manifest = tmp_path / "manifest.json"

    def write_manifest() -> None:
        manifest.write_text(
            json.dumps(
                {
                    "xray_version": "26.3.27",
                    "artifacts": {
                        platform: {
                            "filename": archive.name,
                            "url": "https://example.invalid/Xray-fixture.zip",
                            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        }
                    },
                }
            )
        )

    write_manifest()
    install_root = tmp_path / "install"
    config_dir = tmp_path / "config"
    state_dir = tmp_path / "state"
    env = {
        **os.environ,
        "XRAY_ONE_CLICK_ALLOW_NONROOT": "1",
        "XRAY_NONINTERACTIVE": "1",
        "XRAY_ONE_CLICK_ACTION": "install",
        "XRAY_ONE_CLICK_ARCHIVE": str(archive),
        "XRAY_MANIFEST": str(manifest),
        "XRAY_INSTALL_ROOT": str(install_root),
        "XRAY_CONFIG_DIR": str(config_dir),
        "XRAY_STATE_DIR": str(state_dir),
        "XRAY_SKIP_SYSTEMD": "1",
        "XRAY_PLATFORM": platform,
    }
    first = subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=False
    )
    assert first.returncode == 0, first.stderr + first.stdout
    assert (install_root / "bin/xray").exists()
    assert (state_dir / "current-generation").read_text() == "0\n"

    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.json").write_text('{"inbounds":[]}')
    (state_dir / "current-generation").write_text("7\n")
    _write_archive(archive, "updated")
    write_manifest()
    env["XRAY_ONE_CLICK_ACTION"] = "update"
    second = subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=False
    )
    assert second.returncode == 0, second.stderr + second.stdout
    assert (state_dir / "current-generation").read_text() == "7\n"
    assert (config_dir / "config.json").read_text() == '{"inbounds":[]}'
    version = subprocess.run(
        [str(install_root / "bin/xray"), "version"], capture_output=True, text=True, check=True
    )
    assert "updated" in version.stdout
