from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .errors import DomainError


def exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return Response({"code": exc.code, "message": exc.message, "retryable": exc.retryable, "operation_id": None, "details": exc.details}, status=status.HTTP_409_CONFLICT)
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    detail = response.data.get("detail", "请求失败") if isinstance(response.data, dict) else "请求失败"
    return Response({"code": getattr(exc, "default_code", "REQUEST_ERROR"), "message": detail, "retryable": False, "operation_id": None, "details": {}}, status=response.status_code, headers=response.headers)
