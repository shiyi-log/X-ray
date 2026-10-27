from pathlib import Path


def test_apply_config_clears_transient_systemd_start_limit_before_restart():
    source = (Path(__file__).resolve().parents[2] / "installer/apply-config.sh").read_text()
    reset = "/bin/systemctl reset-failed xray >/dev/null 2>&1 || true"
    restart = "/bin/systemctl restart xray"
    assert reset in source
    assert source.index(reset) < source.index(restart)
