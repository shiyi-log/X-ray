from __future__ import annotations

import logging

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger("xray.health")


@require_GET
def liveness(request):
    return JsonResponse({"status": "ok"})


@require_GET
def readiness(request):
    checks: dict[str, str] = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception:
        logger.exception("readiness database check failed")
        checks["database"] = "unavailable"
    try:
        import redis
        from django.conf import settings
        redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1).ping()
        checks["redis"] = "ok"
    except Exception:
        logger.exception("readiness redis check failed")
        checks["redis"] = "unavailable"
    ready = all(value == "ok" for value in checks.values())
    return JsonResponse({"status": "ok" if ready else "unavailable", "checks": checks}, status=200 if ready else 503)
