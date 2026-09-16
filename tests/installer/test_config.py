from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APPLY = ROOT / "installer" / "apply-config.sh"


def executable(path: Path, content: str) -> Path:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def harness(tmp_path, *, restart_exit=0):
    binary = executable(
        tmp_path / "xray",
        "#!/bin/sh\n"
        "if [ \"$1\" = version ]; then echo 'Xray 26.3.27'; exit 0; fi\n"
        "if [ \"$1\" = run ] && [ \"$2\" = -test ]; then exit 0; fi\n"
        "exit 2\n",
    )
    restart = executable(tmp_path / "restart", f"#!/bin/sh\nexit {restart_exit}\n")
    state = tmp_path / "state"
    config = tmp_path / "config"
    env = {
        **os.environ,
        "XRAY_STATE_DIR": str(state),
        "XRAY_CONFIG_DIR": str(config),
        "XRAY_BINARY": str(binary),
        "XRAY_SERVICE_RESTART_BIN": str(restart),
    }
    return env, state, config


def apply(env, payload):
    return subprocess.run(
        ["bash", str(APPLY)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def request(generation, previous, clients, *, action="normal"):
    return {
        "schema_version": 1,
        "node_id": "11111111-1111-4111-8111-111111111111",
        "generation": generation,
        "expected_previous_generation": previous,
        "config": {"inbounds": [{"settings": {"clients": clients}}]},
        "action": action,
    }


def test_stale_configuration_cannot_overwrite_revocation(tmp_path):
    env, _state, config = harness(tmp_path)
    assert apply(env, request(5, 0, ["new"])).returncode == 0
    stale = apply(env, request(4, 5, ["revoked"]))
    assert stale.returncode == 30
    current = json.loads((config / "config.json").read_text())
    assert current["inbounds"][0]["settings"]["clients"] == ["new"]


def test_config_is_data_and_shell_metacharacters_are_not_executed(tmp_path):
    env, _state, config = harness(tmp_path)
    marker = tmp_path / "executed"
    value = f"$(touch {marker})"
    result = apply(env, request(1, 0, [value]))
    assert result.returncode == 0
    assert not marker.exists()
    assert value in (config / "config.json").read_text()
    assert value not in result.stdout


def test_security_restart_failure_never_restores_revoked_config(tmp_path):
    env, _state, config = harness(tmp_path)
    assert apply(env, request(1, 0, ["old"])).returncode == 0
    failing_env, _state, _config = harness(tmp_path, restart_exit=1)
    failed = apply(failing_env, request(2, 1, [], action="security"))
    assert failed.returncode == 40
    current = json.loads((config / "config.json").read_text())
    assert current["inbounds"][0]["settings"]["clients"] == []
    assert json.loads(failed.stdout)["rollback_performed"] is False
