from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from functools import wraps

from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect

from apps.identity.services import require_admin, require_recent_step_up
from common.errors import DomainError


def json_payload(request) -> dict:
    try:
        value = json.loads(request.body or "{}")
    except (TypeError, ValueError) as exc:
        raise DomainError("INVALID_JSON", "请求体不是有效 JSON", status_code=400) from exc
    if not isinstance(value, dict):
        raise DomainError("INVALID_JSON", "请求体必须是 JSON 对象", status_code=400)
    return value


def error_response(exc: Exception) -> JsonResponse:
    if isinstance(exc, DomainError):
        payload = {
            "code": exc.code,
            "message": exc.message,
            "retryable": exc.retryable,
            "operation_id": None,
            "details": exc.details,
        }
        status = exc.status_code
    elif isinstance(exc, ObjectDoesNotExist):
        payload = {
            "code": "NOT_FOUND",
            "message": "资源不存在",
            "retryable": False,
            "operation_id": None,
            "details": {},
        }
        status = 404
    elif isinstance(exc, IntegrityError):
        payload = {
            "code": "RESOURCE_CONFLICT",
            "message": "资源与现有记录冲突",
            "retryable": False,
            "operation_id": None,
            "details": {},
        }
        status = 409
    elif isinstance(exc, (TypeError, ValueError)):
        payload = {
            "code": "INVALID_REQUEST",
            "message": str(exc) or "请求参数无效",
            "retryable": False,
            "operation_id": None,
            "details": {},
        }
        status = 400
    else:
        payload = {
            "code": "REQUEST_FAILED",
            "message": "请求失败",
            "retryable": False,
            "operation_id": None,
            "details": {},
        }
        status = 500
    return JsonResponse(payload, status=status)


def admin_endpoint(*methods: str, recent: bool = False):
    allowed = {value.upper() for value in methods}

    def decorator(view: Callable):
        @wraps(view)
        def execute(request, *args, **kwargs):
            if request.method not in allowed:
                return error_response(
                    DomainError("METHOD_NOT_ALLOWED", "请求方法不允许", status_code=405)
                )
            try:
                return view(request, *args, **kwargs)
            except Exception as exc:
                return error_response(exc)

        guarded = require_recent_step_up(execute) if recent else require_admin(execute)
        return csrf_protect(wraps(view)(guarded))

    return decorator


def paginated_response(
    request,
    values: Iterable,
    serializer: Callable[[object], dict],
) -> JsonResponse:
    try:
        page = max(1, int(request.GET.get("page", "1")))
        page_size = min(100, max(1, int(request.GET.get("page_size", "25"))))
    except ValueError as exc:
        raise ValueError("page and page_size must be integers") from exc
    if hasattr(values, "count") and hasattr(values, "__getitem__"):
        total = values.count()
        start = (page - 1) * page_size
        items = values[start : start + page_size]
    else:
        materialized = list(values)
        total = len(materialized)
        start = (page - 1) * page_size
        items = materialized[start : start + page_size]
    return JsonResponse(
        {
            "items": [serializer(value) for value in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )
