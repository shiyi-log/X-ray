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
        'if [ "$1" = run ] && [ "$2" = -test ]; then exit 0; fi\n'
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


def test_json_candidate_is_validated_independently_of_temporary_filename(tmp_path):
    env, state, _config = harness(tmp_path)
    # Match the real binary's format selection: random suffixes need explicit JSON.
    executable(
        Path(env["XRAY_BINARY"]),
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "path = pathlib.Path(args[args.index('-config') + 1])\n"
        "explicit = '-format' in args and args[args.index('-format') + 1] == 'json'\n"
        "if path.suffix != '.json' and not explicit: sys.exit(23)\n"
        "json.loads(path.read_text())\n",
    )
    result = apply(env, request(1, 0, []))
    assert result.returncode == 0
    assert (state / "current-generation").read_text().strip() == "1"


def test_tls_files_are_inlined_for_dynamic_user_without_exposing_key(tmp_path):
    env, _state, config = harness(tmp_path)
    certs = tmp_path / "certs"
    certs.mkdir()
    certificate, private = certs / "proxy.crt", certs / "proxy.key"
    certificate.write_text("fixture-certificate\n")
    private.write_text("fixture-private-material\n")
    private.chmod(0o600)
    env["XRAY_TLS_CERT_DIR"] = str(certs)
    payload = request(1, 0, [])
    payload["config"]["inbounds"][0]["streamSettings"] = {
        "tlsSettings": {
            "certificates": [{"certificateFile": str(certificate), "keyFile": str(private)}]
        }
    }
    result = apply(env, payload)
    assert result.returncode == 0
    entry = json.loads((config / "config.json").read_text())["inbounds"][0]["streamSettings"][
        "tlsSettings"
    ]["certificates"][0]
    assert entry["key"] == ["fixture-private-material"]
    assert "keyFile" not in entry
    assert "fixture-private-material" not in result.stdout + result.stderr
    assert (config / "config.json").stat().st_mode & 0o777 == 0o600


def test_certificate_path_outside_node_directory_fails_closed(tmp_path):
    env, _state, _config = harness(tmp_path)
    env["XRAY_TLS_CERT_DIR"] = str(tmp_path / "certs")
    other = tmp_path / "outside.key"
    other.write_text("fixture-only")
    payload = request(1, 0, [])
    payload["config"]["inbounds"][0]["streamSettings"] = {
        "tlsSettings": {"certificates": [{"keyFile": str(other)}]}
    }
    result = apply(env, payload)
    assert result.returncode == 20
    assert json.loads(result.stdout)["error_code"] == "CERTIFICATE_INVALID"
