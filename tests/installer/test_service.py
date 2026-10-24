"""Opt-in real systemd gate; run only on an authorized disposable Linux host."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4


@unittest.skipUnless(
    sys.platform == "linux" and os.getenv("XRAY_RUN_SYSTEMD_TESTS") == "1",
    "requires an explicitly selected disposable Linux systemd host",
)
class SystemdCredentialTest(unittest.TestCase):
    def test_dynamic_service_user_can_read_root_only_configuration(self):
        self.assertEqual(os.geteuid(), 0)
        source = Path(os.environ.get(
            "XRAY_SERVICE_FILE",
            str(Path(__file__).resolve().parents[2] / "installer/xray.service"),
        )).read_text()
        suffix = uuid4().hex[:8]
        user = f"xray-check-{suffix}"
        name = f"xray-credential-check-{suffix}.service"
        unit = Path("/run/systemd/system") / name
        with tempfile.TemporaryDirectory(prefix="xray-systemd-check-", dir="/run") as temporary:
            root = Path(temporary)
            config = root / "config.json"
            config.write_text('{"inbounds":[],"outbounds":[{"protocol":"freedom"}]}')
            config.chmod(0o600)
            source = source.replace("User=xray", f"User={user}")
            source = source.replace("Group=xray", f"Group={user}")
            source = source.replace("Type=simple", "Type=oneshot\nRemainAfterExit=yes")
            lines = []
            for line in source.splitlines():
                if line.startswith("ExecStart="):
                    line = "ExecStart=/usr/bin/test -r ${CREDENTIALS_DIRECTORY}/xray-config"
                elif line.startswith("ReadWritePaths="):
                    line = f"ReadWritePaths={root}"
                elif line.startswith("LoadCredential="):
                    line = f"LoadCredential=xray-config:{config}"
                lines.append(line)
            try:
                unit.write_text("\n".join(lines) + "\n")
                self._systemctl("daemon-reload")
                self._systemctl("start", name)
                self._systemctl("is-active", "--quiet", name)
                self.assertEqual(config.stat().st_mode & 0o777, 0o600)
                self.assertEqual(config.stat().st_uid, 0)
            finally:
                subprocess.run(["systemctl", "stop", name], capture_output=True)
                unit.unlink(missing_ok=True)
                self._systemctl("daemon-reload")

    def _systemctl(self, *arguments):
        result = subprocess.run(
            ["systemctl", *arguments], capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, "systemd permission gate failed")


if __name__ == "__main__":
    unittest.main()
