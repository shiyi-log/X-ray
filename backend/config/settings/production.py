import os
from .base import *  # noqa: F403

if SECRET_KEY == "development-only-change-me":
    raise RuntimeError("XRAY_SECRET_KEY must be set in production")
if not ALLOWED_HOSTS:
    raise RuntimeError("XRAY_ALLOWED_HOSTS must contain at least one host")
if not os.getenv("XRAY_DATABASE_URL"):
    raise RuntimeError("XRAY_DATABASE_URL must be set in production")
DEBUG = False
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
