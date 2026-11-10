import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_SCRIPT = """
import json
from config.settings import development

print(json.dumps({
    "session_cookie_name": development.SESSION_COOKIE_NAME,
    "csrf_cookie_name": development.CSRF_COOKIE_NAME,
    "session_cookie_secure": development.SESSION_COOKIE_SECURE,
    "csrf_cookie_secure": development.CSRF_COOKIE_SECURE,
}))
"""


def development_cookie_settings(overrides=None):
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(BACKEND_ROOT),
        "DJANGO_SETTINGS_MODULE": "config.settings.development",
        "XRAY_ENV": "test",
        "XRAY_DEBUG": "0",
    }
    environment.update(overrides or {})
    result = subprocess.run(
        [sys.executable, "-c", SETTINGS_SCRIPT],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, "development settings subprocess failed"
    return json.loads(result.stdout)


def test_development_settings_use_http_compatible_cookie_defaults():
    settings = development_cookie_settings()

    assert settings == {
        "session_cookie_name": "xray_dev_session",
        "csrf_cookie_name": "xray_dev_csrf",
        "session_cookie_secure": False,
        "csrf_cookie_secure": False,
    }


def test_development_settings_preserve_explicit_secure_cookie_opt_in():
    settings = development_cookie_settings(
        {
            "XRAY_SESSION_COOKIE_SECURE": "true",
            "XRAY_CSRF_COOKIE_SECURE": "true",
        }
    )

    assert settings["session_cookie_secure"] is True
    assert settings["csrf_cookie_secure"] is True
