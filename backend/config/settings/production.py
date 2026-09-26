import os

from .base import *  # noqa: F403
from .base import ALLOWED_HOSTS as BASE_ALLOWED_HOSTS
from .base import SECRET_KEY as BASE_SECRET_KEY

if BASE_SECRET_KEY == "development-only-change-me":
    raise RuntimeError("XRAY_SECRET_KEY must be set in production")
if not BASE_ALLOWED_HOSTS:
    raise RuntimeError("XRAY_ALLOWED_HOSTS must contain at least one host")

# The password-only test bypass is never allowed in production.
XRAY_DISABLE_TOTP = False
if not os.getenv("XRAY_DATABASE_URL"):
    raise RuntimeError("XRAY_DATABASE_URL must be set in production")
DEBUG = False
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
