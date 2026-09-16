"""Settings for isolated PostgreSQL integration tests."""
from __future__ import annotations
import os
from .base import *  # noqa: F403
from .base import database_from_url

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
