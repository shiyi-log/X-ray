from .base import *  # noqa: F403
from .base import SECRET_KEY as BASE_SECRET_KEY
from .base import env_bool

DEBUG = True
SECRET_KEY = (
    BASE_SECRET_KEY
    if BASE_SECRET_KEY != "development-only-change-me"
    else "local-development-only"
)
SESSION_COOKIE_NAME = "xray_dev_session"
CSRF_COOKIE_NAME = "xray_dev_csrf"
SESSION_COOKIE_SECURE = env_bool("XRAY_SESSION_COOKIE_SECURE", False)
CSRF_COOKIE_SECURE = env_bool("XRAY_CSRF_COOKIE_SECURE", False)
