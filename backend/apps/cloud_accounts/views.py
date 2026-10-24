from __future__ import annotations

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from apps.identity.services import require_admin, require_recent_step_up
from common.errors import DomainError
from common.regions import normalize_region
from providers.base import SecretInput

from .models import CloudAccount
from .serializers import CloudAccountSerializer
from .services import (
    capabilities,
    create_account,
    rotate_credentials,
    set_account_enabled,
    validate_account,
)


def _payload(request):
    try:
        value = json.loads(request.body or "{}")
    except (TypeError, ValueError) as exc:
        raise DomainError("INVALID_JSON", "请求体不是有效 JSON", status_code=400) from exc
    if not isinstance(value, dict):
        raise DomainError("INVALID_JSON", "请求体必须是 JSON 对象", status_code=400)
    return value


def _error(exc: Exception) -> JsonResponse:
    if isinstance(exc, DomainError):
        code, message, retryable, details, status = (
            exc.code,
            exc.message,
            exc.retryable,
            exc.details,
            exc.status_code,
        )
    elif isinstance(exc, ValueError):
        code, message, retryable, details, status = (
            "INVALID_REQUEST",
            str(exc),
            False,
            {},
            400,
        )
    else:
        code, message, retryable, details, status = (
            "REQUEST_FAILED",
            "请求失败",
            False,
            {},
            500,
        )
    return JsonResponse(
        {
            "code": code,
            "message": message,
            "retryable": retryable,
            "operation_id": None,
            "details": details,
        },
        status=status,
    )


@csrf_protect
@require_admin
def collection(request):
    if request.method == "GET":
        accounts = CloudAccount.objects.all()
        return JsonResponse(
            {
                "items": [
                    CloudAccountSerializer.to_representation(account) for account in accounts
                ],
                "total": accounts.count(),
                "page": 1,
                "page_size": accounts.count(),
            }
        )
    if request.method == "POST":
        try:
            name, region, raw = CloudAccountSerializer.validate_create(_payload(request))
            account = create_account(
                name=name,
                region=region,
                credentials=SecretInput(provider=raw["provider"], fields=raw["fields"]),
            )
            return JsonResponse(CloudAccountSerializer.to_representation(account), status=201)
        except (DomainError, ValueError) as exc:
            return _error(exc)
    return _error(DomainError("METHOD_NOT_ALLOWED", "只允许 GET 或 POST", status_code=405))


@csrf_protect
@require_admin
def detail(request, account_id):
    try:
        account = CloudAccount.objects.get(pk=account_id)
    except CloudAccount.DoesNotExist:
        return _error(DomainError("NOT_FOUND", "云账号不存在", status_code=404))
    if request.method == "GET":
        return JsonResponse(CloudAccountSerializer.to_representation(account))
    if request.method == "DELETE":
        return _error(DomainError("METHOD_NOT_ALLOWED", "云账号不能硬删除", status_code=405))
    if request.method != "PATCH":
        return _error(DomainError("METHOD_NOT_ALLOWED", "只允许 GET 或 PATCH", status_code=405))
    try:
        changes = CloudAccountSerializer.validate_patch(_payload(request))
        if "name" in changes:
            account.name = changes["name"]
        if "enabled" in changes:
            account = set_account_enabled(account.pk, enabled=changes["enabled"])
        if "name" in changes:
            account.save(update_fields=["name", "updated_at"])
        return JsonResponse(CloudAccountSerializer.to_representation(account))
    except (DomainError, ValueError) as exc:
        return _error(exc)


@csrf_protect
@require_POST
@require_admin
def validate(request, account_id):
    try:
        payload = _payload(request)
        identity = validate_account(account_id, region=normalize_region(payload.get("region")))
        return JsonResponse(
            {
                "external_account_id": identity.external_account_id,
                "principal_id": identity.principal_id,
                "verified_at": identity.verified_at.isoformat(),
            }
        )
    except (DomainError, ValueError) as exc:
        return _error(exc)


@csrf_protect
@require_POST
@require_recent_step_up
def rotate(request, account_id):
    try:
        payload = _payload(request)
        provider = str(payload.get("provider") or "")
        fields = payload.get("credentials")
        if not isinstance(fields, dict):
            raise ValueError("credentials is required")
        account = rotate_credentials(
            account_id,
            credentials=SecretInput(provider=provider, fields=fields),
            region=normalize_region(payload.get("region")),
            expected_version=payload.get("expected_version"),
        )
        return JsonResponse(CloudAccountSerializer.to_representation(account))
    except (DomainError, ValueError) as exc:
        return _error(exc)


@require_GET
@require_admin
def capability_list(request, account_id):
    try:
        values = capabilities(account_id, region=normalize_region(request.GET.get("region")))
        return JsonResponse(
            {
                "items": [
                    {
                        "name": value.name,
                        "status": value.status,
                        "regions": list(value.regions),
                        "plans": list(value.plans),
                        "evidence_url": value.evidence_url,
                        "checked_at": value.checked_at.isoformat(),
                        "document_verified": value.document_verified,
                        "stub_verified": value.stub_verified,
                        "live_verified": value.live_verified,
                        "reason": value.reason,
                    }
                    for value in values
                ]
            }
        )
    except (DomainError, ValueError) as exc:
        return _error(exc)
