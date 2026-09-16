from .base import *  # noqa: F403
DEBUG = True
SECRET_KEY = SECRET_KEY if SECRET_KEY != "development-only-change-me" else "local-development-only"
