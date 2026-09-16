"""Least-privilege settings for the public read-only subscription process."""

from .production import *  # noqa: F403

ROOT_URLCONF = "config.subscription_urls"
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]
