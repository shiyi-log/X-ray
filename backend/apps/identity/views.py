from __future__ import annotations

import json
from datetime import datetime
from functools import wraps

import pyotp
from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from apps.identity.gate_settings import (
    _UNSET,
    node_automation_settings,
    node_status_sync_setting,
    provider_identity_network_setting,
    set_node_automation_settings,
    set_node_status_sync_settings,
    set_provider_identity_network_enabled,
)
from common.admin_api import admin_endpoint, json_payload
from common.crypto import configured_secret_store
from common.errors import DomainError

from .services import (
    complete_recovery,
    complete_totp,
    complete_totp_setup,
    local_one_click_login,
    local_one_click_login_enabled,
    password_login,
    record_step_up,
    require_admin,
    require_recent_step_up,
    revoke_all,
    session_status,
    setup_totp,
)


def _json(request) -> dict:
    try:
        payload = json.loads(request.body or "{}")
    except (TypeError, ValueError) as exc:
        raise DomainError("INVALID_JSON", "请求体不是有效 JSON", status_code=400) from exc
    if not isinstance(payload, dict):
        raise DomainError("INVALID_JSON", "请求体必须是 JSON 对象", status_code=400)
    return payload


def _error(exc: DomainError) -> JsonResponse:
    return JsonResponse(
        {
            "code": exc.code,
            "message": exc.message,
            "retryable": exc.retryable,
            "operation_id": None,
            "details": exc.details,
        },
        status=exc.status_code,
    )


def _run(fn):
    @wraps(fn)
    def wrapped(request, *args, **kwargs):
        try:
            return fn(request, *args, **kwargs)
        except DomainError as exc:
            return _error(exc)

    return wrapped


@ensure_csrf_cookie
@require_GET
def csrf(request):
    return JsonResponse({"csrf_token": get_token(request)})


@require_GET
def local_login_status(request):
    return JsonResponse({"enabled": local_one_click_login_enabled(request)})


@csrf_protect
@require_POST
@_run
def local_login(request):
    return JsonResponse(local_one_click_login(request))


@csrf_protect
@require_POST
@_run
def login(request):
    payload = _json(request)
    username = str(payload.get("username") or "")
    password = str(payload.get("password") or "")
    if not username or not password:
        raise DomainError("AUTH_INVALID", "用户名或密码错误", status_code=401)
    return JsonResponse(password_login(request, username, password))


@csrf_protect
@require_POST
@_run
def totp_setup(request):
    payload = _json(request)
    return JsonResponse(setup_totp(request, str(payload.get("challenge_id") or "")))


@csrf_protect
@require_POST
@_run
def totp_confirm(request):
    payload = _json(request)
    return JsonResponse(
        complete_totp_setup(
            request,
            str(payload.get("challenge_id") or ""),
            str(payload.get("code") or ""),
        )
    )


@csrf_protect
@require_POST
@_run
def totp_verify(request):
    payload = _json(request)
    return JsonResponse(
        complete_totp(
            request,
            str(payload.get("challenge_id") or ""),
            str(payload.get("code") or ""),
        )
    )


@csrf_protect
@require_POST
@_run
def recovery_code(request):
    payload = _json(request)
    return JsonResponse(
        complete_recovery(
            request,
            str(payload.get("challenge_id") or ""),
            str(payload.get("code") or ""),
        )
    )


@require_GET
def session(request):
    return JsonResponse(session_status(request))


@csrf_protect
@require_POST
@_run
def logout(request):
    request.session.flush()
    return JsonResponse({"authenticated": False})


@csrf_protect
@require_POST
@require_admin
def logout_all(request):
    revoke_all(request.xray_admin)
    request.session.flush()
    return JsonResponse({"authenticated": False})


@csrf_protect
@require_POST
@_run
@require_admin
def step_up(request):
    payload = _json(request)
    admin = request.xray_admin
    if not admin.check_password(str(payload.get("password") or "")):
        raise DomainError("STEP_UP_INVALID", "身份验证失败", status_code=401)
    if admin.totp_secret_envelope:
        code = str(payload.get("code") or "")
        secret = (
            configured_secret_store()
            .decrypt(
                admin.totp_secret_envelope,
                purpose="control",
                aad=f"totp:{admin.pk}".encode(),
            )
            .decode()
        )
        if not pyotp.TOTP(secret).verify(code, valid_window=0):
            raise DomainError("STEP_UP_INVALID", "身份验证失败", status_code=401)
    until = record_step_up(request, admin)
    return JsonResponse({"recent_auth_until": until.isoformat()})


@csrf_protect
@require_POST
@_run
@require_recent_step_up
def change_password(request):
    payload = _json(request)
    admin = request.xray_admin
    old_password = str(payload.get("old_password") or "")
    new_password = str(payload.get("new_password") or "")
    if not admin.check_password(old_password):
        raise DomainError("PASSWORD_INVALID", "当前密码错误", status_code=401)
    if len(new_password) < 12:
        raise DomainError("PASSWORD_TOO_SHORT", "新密码至少需要 12 个字符", status_code=400)
    admin.set_password(new_password)
    admin.session_version += 1
    admin.save(update_fields=["password", "session_version", "updated_at"])
    revoke_all(admin)
    request.session.flush()
    return JsonResponse({"authenticated": False})


@admin_endpoint("GET", "PATCH")
def system(request):
    if request.method == "PATCH":
        payload = json_payload(request)
        allowed = {
            "provider_identity_network_enabled",
            "node_status_sync_enabled",
            "node_status_sync_interval_minutes",
            "node_pool_sync_enabled",
            "node_pool_sync_interval_minutes",
            "node_pool_sync_creation_templates",
            "node_daily_restart_enabled",
            "node_daily_restart_time",
            "node_daily_restart_timezone",
            "usage_sync_enabled",
            "usage_sync_interval_minutes",
        }
        if not payload or set(payload) - allowed:
            raise ValueError("at least one supported system setting is required")
        automation_fields = allowed - {
            "provider_identity_network_enabled",
            "node_status_sync_enabled",
            "node_status_sync_interval_minutes",
        }
        automation_values = {
            key: value for key, value in payload.items() if key in automation_fields
        }
        with transaction.atomic():
            if automation_values:
                current = node_automation_settings()
                pool_enabled = payload.get(
                    "node_pool_sync_enabled", current["node_pool_sync"]["enabled"]
                )
                restart_enabled = payload.get(
                    "node_daily_restart_enabled", current["node_daily_restart"]["enabled"]
                )
                automation_sensitive = (
                    pool_enabled
                    and bool(
                        {
                            "node_pool_sync_enabled",
                            "node_pool_sync_interval_minutes",
                            "node_pool_sync_creation_templates",
                        }
                        & automation_values.keys()
                    )
                ) or (
                    restart_enabled
                    and bool(
                        {
                            "node_daily_restart_enabled",
                            "node_daily_restart_time",
                            "node_daily_restart_timezone",
                        }
                        & automation_values.keys()
                    )
                )
                if automation_sensitive:
                    recent = request.session.get("recent_auth_until")
                    try:
                        valid_recent_auth = bool(
                            recent and datetime.now().astimezone() < datetime.fromisoformat(recent)
                        )
                    except ValueError:
                        valid_recent_auth = False
                    if not valid_recent_auth:
                        raise DomainError(
                            "STEP_UP_REQUIRED", "请重新验证身份", status_code=403, retryable=True
                        )
                set_node_automation_settings(actor=request.xray_admin, values=automation_values)
            if "provider_identity_network_enabled" in payload:
                enabled = payload["provider_identity_network_enabled"]
                if not isinstance(enabled, bool):
                    raise ValueError("provider_identity_network_enabled must be a boolean")
                set_provider_identity_network_enabled(enabled=enabled, actor=request.xray_admin)
            if {"node_status_sync_enabled", "node_status_sync_interval_minutes"} & set(payload):
                set_node_status_sync_settings(
                    actor=request.xray_admin,
                    enabled=payload.get("node_status_sync_enabled", _UNSET),
                    interval_minutes=payload.get("node_status_sync_interval_minutes", _UNSET),
                )

    return JsonResponse(
        {
            "version": open(settings.BASE_DIR.parent / "VERSION", encoding="utf-8").read().strip()
            if (settings.BASE_DIR.parent / "VERSION").exists()
            else "unknown",
            "environment": getattr(settings, "XRAY_ENV", "unknown"),
            "debug": bool(settings.DEBUG),
            "allowed_hosts": list(settings.ALLOWED_HOSTS),
            "csrf_trusted_origins": list(settings.CSRF_TRUSTED_ORIGINS),
            "provider_identity_network": provider_identity_network_setting(),
            "node_status_sync": node_status_sync_setting(),
            **node_automation_settings(),
        }
    )
