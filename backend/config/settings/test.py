"""Settings for isolated PostgreSQL integration tests."""

from __future__ import annotations

import os

from .base import *  # noqa: F403
from .base import database_from_url, env_list

TEST_DATABASE_URL = os.getenv("XRAY_TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    raise RuntimeError("XRAY_TEST_DATABASE_URL is required; tests must use dedicated PostgreSQL")
TEST_DATABASE = database_from_url(TEST_DATABASE_URL)
if TEST_DATABASE["NAME"] != "xray_test":
    raise RuntimeError("XRAY_TEST_DATABASE_URL must target the xray_test database")
DATABASES = {"default": TEST_DATABASE}
DEBUG = False
SECRET_KEY = "test-only-not-for-production"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_NAME = "xray_test_session"
CSRF_COOKIE_NAME = "xray_test_csrf"
# Keep direct local test-server runs compatible with the Vite dev origin. The
# launcher overrides this with the dynamically selected frontend port.
CSRF_TRUSTED_ORIGINS = list(  # noqa: F405
    dict.fromkeys(
        [
            *env_list("XRAY_CSRF_TRUSTED_ORIGINS"),
            "http://127.0.0.1:9528",
            "http://localhost:9528",
        ]
    )
)
# Deliberately test-only; production settings force this to False.
XRAY_DISABLE_TOTP = XRAY_ENV == "test" and env_bool("XRAY_DISABLE_TOTP", False)  # noqa: F405
XRAY_LOCAL_ONE_CLICK_LOGIN = XRAY_ENV == "test" and env_bool(  # noqa: F405
    "XRAY_LOCAL_ONE_CLICK_LOGIN", True
)
