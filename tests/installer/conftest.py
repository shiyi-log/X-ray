from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


@pytest.fixture
def isolated_installer_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provide fixture ZIP extraction without host packages or apt writes."""
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    unzip_called = tools_dir / "unzip.called"
    apt_get_called = tools_dir / "apt-get.called"

    unzip = tools_dir / "unzip"
    unzip.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "import zipfile\n"
        f"from pathlib import Path\nPath({str(unzip_called)!r}).touch()\n"
        "args = sys.argv[1:]\n"
        "if len(args) != 4 or args[0] != '-q' or args[2] != '-d':\n"
        "    raise SystemExit('unexpected unzip arguments')\n"
        "with zipfile.ZipFile(args[1]) as archive:\n"
        "    archive.extractall(args[3])\n"
        "executable = Path(args[3]) / 'xray'\n"
        "if executable.is_file():\n"
        "    executable.chmod(0o755)\n",
        encoding="utf-8",
    )
    unzip.chmod(0o755)

    apt_get = tools_dir / "apt-get"
    apt_get.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"from pathlib import Path\nPath({str(apt_get_called)!r}).touch()\n"
        "print('apt-get must not run in installer integration tests', file=sys.stderr)\n"
        "raise SystemExit(97)\n",
        encoding="utf-8",
    )
    apt_get.chmod(0o755)

    monkeypatch.setenv("PATH", os.pathsep.join((str(tools_dir), os.environ["PATH"])))
    return {"unzip_called": unzip_called, "apt_get_called": apt_get_called}
