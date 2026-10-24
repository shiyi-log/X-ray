import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_repeat_installation_preserves_generation_and_configuration(tmp_path):
    archive = tmp_path / "test-bundle.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        executable = zipfile.ZipInfo("xray")
        executable.external_attr = 0o100755 << 16
        bundle.writestr(executable, "#!/bin/sh\necho 'Xray 26.3.27 fixture'\n")
        bundle.writestr("geoip.dat", b"test fixture")
        bundle.writestr("geosite.dat", b"test fixture")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "xray_version": "26.3.27",
        "artifacts": {"linux-amd64": {
            "filename": archive.name,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        }},
    }))
    state = tmp_path / "state"
    state.mkdir()
    generation = state / "current-generation"
    generation.write_text("7\n")
    config = tmp_path / "config"
    config.mkdir()
    current = config / "config.json"
    current.write_text('{"inbounds":[]}')
    env = {
        **os.environ, "XRAY_MANIFEST": str(manifest), "XRAY_PLATFORM": "linux-amd64",
        "XRAY_INSTALL_ROOT": str(tmp_path / "install"), "XRAY_CONFIG_DIR": str(config),
        "XRAY_STATE_DIR": str(state), "XRAY_SKIP_SYSTEMD": "1",
    }
    result = subprocess.run(
        ["bash", str(ROOT / "installer/install.sh"), str(archive)],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert generation.read_text() == "7\n"
    assert current.read_text() == '{"inbounds":[]}'
