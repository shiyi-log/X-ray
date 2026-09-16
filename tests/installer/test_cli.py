import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_manifest_is_version_and_hash_pinned_without_latest_urls():
    manifest = json.loads((ROOT / "installer" / "manifest.json").read_text())
    assert manifest["xray_version"] == "26.3.27"
    assert manifest["license"] == "MPL-2.0"
    assert set(manifest["artifacts"]) >= {"linux-amd64", "linux-arm64", "darwin-arm64"}
    for artifact in manifest["artifacts"].values():
        assert len(artifact["sha256"]) == 64
        assert "/v26.3.27/" in artifact["url"]
        assert "latest" not in artifact["url"]


def test_installer_scripts_never_reference_latest_release():
    for name in ("install.sh", "apply-config.sh", "verify.sh"):
        content = (ROOT / "installer" / name).read_text()
        assert "releases/latest" not in content
        assert "curl " not in content
