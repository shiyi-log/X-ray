from .base import *  # noqa: F403
from .base import SECRET_KEY as BASE_SECRET_KEY

DEBUG = True
SECRET_KEY = (
    BASE_SECRET_KEY
    if BASE_SECRET_KEY != "development-only-change-me"
    else "local-development-only"
)
