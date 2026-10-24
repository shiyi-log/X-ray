from __future__ import annotations

from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError
from common.errors import DomainError


def map_provider_error(provider: str, error: Exception, *, write_started: bool) -> DomainError:
    request_id = None
    provider_code = None
    if isinstance(error, ClientError):
        response = error.response or {}
        provider_code = str(response.get("Error", {}).get("Code") or "")[:80] or None
        request_id = str(response.get("ResponseMetadata", {}).get("RequestId") or "")[:120] or None
    elif hasattr(error, "request_id"):
        request_id = str(getattr(error, "request_id"))[:120]
    details = {"provider": provider, "provider_code": provider_code, "request_id": request_id}
    if (
        isinstance(error, (EndpointConnectionError, ReadTimeoutError, TimeoutError))
        and write_started
    ):
        return DomainError(
            "CLOUD_WRITE_OUTCOME_UNKNOWN",
            "云写入结果未知，需要对账",
            retryable=False,
            details=details,
        )
    code = (provider_code or "").lower()
    if provider == "aws_lightsail" and code == "notfoundexception" and not write_started:
        return DomainError(
            "RESOURCE_NOT_FOUND",
            "云资源不存在",
            details=details,
            status_code=404,
        )
    if "access" in code or "permission" in code or "unauthorized" in code:
        return DomainError(
            "CLOUD_PERMISSION_DENIED",
            "云凭据没有所需权限",
            details=details,
            status_code=403,
        )
    if "throttl" in code or "limit" in code:
        return DomainError(
            "CLOUD_THROTTLED",
            "云服务请求受限",
            retryable=True,
            details=details,
            status_code=429,
        )
    if "invalid" in code or "param" in code:
        return DomainError(
            "CLOUD_INVALID_ARGUMENT",
            "云请求参数无效",
            details=details,
            status_code=400,
        )
    return DomainError(
        "CLOUD_PROVIDER_ERROR",
        "云服务请求失败",
        retryable=not write_started,
        details=details,
    )
