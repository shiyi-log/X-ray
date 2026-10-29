"""Shared Django settings for the isolated X-ray manager backend."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parents[2]
XRAY_ENV = os.getenv("XRAY_ENV", "development")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: tuple[str, ...] = ()) -> list[str]:
    value = os.getenv(name)
    return (
        list(default)
        if value is None
        else [item.strip() for item in value.split(",") if item.strip()]
    )


def database_from_url(value: str) -> dict[str, object]:
    parsed = urlparse(value)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("XRAY_DATABASE_URL must use postgres:// or postgresql://")
    if not parsed.path or parsed.path == "/":
        raise ValueError("XRAY_DATABASE_URL must include a database name")
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "127.0.0.1",
        "PORT": str(parsed.port or 5432),
        "CONN_MAX_AGE": int(os.getenv("XRAY_DB_CONN_MAX_AGE", "60")),
        "CONN_HEALTH_CHECKS": True,
    }


SECRET_KEY = os.getenv("XRAY_SECRET_KEY", "development-only-change-me")
DEBUG = env_bool("XRAY_DEBUG", False)
ALLOWED_HOSTS = env_list("XRAY_ALLOWED_HOSTS", ("localhost", "127.0.0.1"))
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "apps.identity",
    "apps.audit",
    "apps.cloud_accounts",
    "apps.operations",
    "apps.nodes",
    "apps.subscriptions",
]
AUTH_USER_MODEL = "identity.SuperAdmin"
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {
    "default": database_from_url(
        os.getenv(
            "XRAY_DATABASE_URL",
            "postgresql://xray:xray@127.0.0.1:5432/xray",
        )
    )
}
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_COOKIE_NAME = "__Host-xray_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = env_bool("XRAY_SESSION_COOKIE_SECURE", not DEBUG)
SESSION_COOKIE_SAMESITE = "Strict"
SESSION_COOKIE_PATH = "/"
SESSION_COOKIE_AGE = 60 * 30
SESSION_SAVE_EVERY_REQUEST = True
CSRF_COOKIE_NAME = "__Host-xray_csrf"
CSRF_COOKIE_SECURE = env_bool("XRAY_CSRF_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_PATH = "/"
CSRF_TRUSTED_ORIGINS = env_list("XRAY_CSRF_TRUSTED_ORIGINS")
CSRF_FAILURE_VIEW = "common.api.csrf_failure"
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
AUTH_SESSION_IDLE_SECONDS = 30 * 60
AUTH_SESSION_ABSOLUTE_SECONDS = 12 * 60 * 60
AUTH_STEP_UP_SECONDS = 5 * 60
MFA_CHALLENGE_SECONDS = 5 * 60
AUTH_RATE_LIMIT_WINDOW_SECONDS = 60
AUTH_RATE_LIMIT_MAX_FAILURES = 10
REDIS_URL = os.getenv("XRAY_REDIS_URL", "redis://127.0.0.1:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
REST_FRAMEWORK = {
    "EXCEPTION_HANDLER": "common.api.exception_handler",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "X-ray Manager API",
    "DESCRIPTION": "Private administrator API. Secrets are write-only or delivered once.",
    "VERSION": "0.7.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "POSTPROCESSING_HOOKS": ["config.openapi.inject_contract"],
}
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"mask_secrets": {"()": "common.logging.SecretMaskFilter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "filters": ["mask_secrets"]}},
    "loggers": {
        "xray": {"handlers": ["console"], "level": os.getenv("XRAY_LOG_LEVEL", "INFO")},
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# Explicit node transport configuration; raw keys never enter settings or logs.
XRAY_NODE_TRANSPORT_FACTORY = os.getenv("XRAY_NODE_TRANSPORT_FACTORY", "")
XRAY_USAGE_FETCHER = os.getenv("XRAY_USAGE_FETCHER", "")
XRAY_ALLOW_REGIONAL_DEFAULT_KEY = env_bool("XRAY_ALLOW_REGIONAL_DEFAULT_KEY", False)
XRAY_PUBLIC_SUBSCRIPTION_BASE_URL = os.getenv("XRAY_PUBLIC_SUBSCRIPTION_BASE_URL", "")
CELERY_BEAT_SCHEDULE = {
    "subscription-usage-and-limits": {
        "task": "apps.subscriptions.tasks.refresh_usage_and_limits", "schedule": 60.0,
    },
}
