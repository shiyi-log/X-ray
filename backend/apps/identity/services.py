from __future__ import annotations

import hashlib
import ipaddress
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import wraps
from urllib.parse import urlsplit

import pyotp
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.core.exceptions import DisallowedHost
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone

from common.crypto import configured_secret_store
from common.errors import DomainError

from .models import AdminSession, MFAChallenge, SuperAdmin


def request_ip(request) -> str | None:
    """Use the socket peer; proxy headers are not trusted by the app."""
    return request.META.get("REMOTE_ADDR") or None


def local_one_click_login_enabled(request) -> bool:
    if getattr(settings, "XRAY_ENV", "") != "test" or not getattr(
        settings, "XRAY_LOCAL_ONE_CLICK_LOGIN", False
    ):
        return False
    try:
        peer = ipaddress.ip_address(request_ip(request) or "")
        host = urlsplit(f"//{request.get_host()}").hostname or ""
        host_is_loopback = host.lower() == "localhost" or ipaddress.ip_address(
            host
        ).is_loopback
    except (ValueError, DisallowedHost):
        return False
    return peer.is_loopback and host_is_loopback


def _user_agent_hash(request) -> str:
    return hashlib.sha256((request.META.get("HTTP_USER_AGENT") or "").encode()).hexdigest()


def _session_binding(request) -> str:
    nonce = request.session.get("xray_challenge_binding")
    if not nonce:
        nonce = secrets.token_urlsafe(24)
        request.session["xray_challenge_binding"] = nonce
    return hashlib.sha256(nonce.encode()).hexdigest()


def _rate_key(username: str, ip: str | None) -> str:
    raw = f"{username.lower()}|{ip or '-'}"
    return "xray:auth:failure:" + hashlib.sha256(raw.encode()).hexdigest()


def _record_failure(username: str, ip: str | None) -> None:
    key = _rate_key(username, ip)
    try:
        if cache.add(key, 1, timeout=settings.AUTH_RATE_LIMIT_WINDOW_SECONDS):
            return
        cache.incr(key)
    except Exception:
        # Authentication remains available if the optional limiter backend is down.
        return


def _too_many_failures(username: str, ip: str | None) -> bool:
    try:
        return int(cache.get(_rate_key(username, ip), 0)) >= settings.AUTH_RATE_LIMIT_MAX_FAILURES
    except Exception:
        return False


def _challenge_from_request(request, challenge_id: str | None) -> MFAChallenge:
    session_id = request.session.get("mfa_challenge_id")
    if not challenge_id or str(session_id) != str(challenge_id):
        raise DomainError("MFA_CHALLENGE_REQUIRED", "请先完成密码验证", status_code=401)
    try:
        challenge = MFAChallenge.objects.select_related("admin").get(pk=challenge_id)
    except MFAChallenge.DoesNotExist as exc:
        raise DomainError("MFA_CHALLENGE_INVALID", "验证挑战已失效", status_code=401) from exc
    if challenge.used_at or challenge.expires_at <= timezone.now():
        raise DomainError("MFA_CHALLENGE_EXPIRED", "验证挑战已失效", status_code=401)
    if challenge.session_binding != _session_binding(request):
        raise DomainError("MFA_CHALLENGE_INVALID", "验证挑战与当前会话不匹配", status_code=401)
    if challenge.source_ip and challenge.source_ip != request_ip(request):
        raise DomainError("MFA_CHALLENGE_INVALID", "验证来源发生变化", status_code=401)
    return challenge


def password_login(request, username: str, password: str) -> dict:
    ip = request_ip(request)
    if _too_many_failures(username, ip):
        raise DomainError(
            "AUTH_RATE_LIMITED",
            "登录尝试过于频繁，请稍后重试",
            retryable=True,
            status_code=429,
        )
    admin = authenticate(request, username=username, password=password)
    if admin is None or not admin.is_active:
        _record_failure(username, ip)
        raise DomainError("AUTH_INVALID", "用户名或密码错误", status_code=401)
    if admin.locked_until and admin.locked_until > timezone.now():
        raise DomainError(
            "AUTH_RATE_LIMITED",
            "登录暂时受限，请稍后重试",
            retryable=True,
            status_code=429,
        )
    if not admin.totp_secret_envelope:
        return _start_session(request, admin, None)
    challenge = MFAChallenge.objects.create(
        admin=admin,
        source_ip=ip,
        session_binding=_session_binding(request),
        expires_at=timezone.now() + timedelta(seconds=settings.MFA_CHALLENGE_SECONDS),
    )
    if getattr(settings, "XRAY_ENV", "") == "test" and getattr(
        settings, "XRAY_DISABLE_TOTP", False
    ):
        response = _start_session(request, admin, challenge)
        response.update(mfa_required=False, totp_setup_required=False)
        return response
    request.session["mfa_challenge_id"] = str(challenge.pk)
    request.session.set_expiry(settings.MFA_CHALLENGE_SECONDS)
    return {
        "challenge_id": str(challenge.pk),
        "mfa_required": bool(admin.totp_secret_envelope),
        "totp_setup_required": not bool(admin.totp_secret_envelope),
        "expires_at": challenge.expires_at.isoformat(),
    }


def setup_totp(request, challenge_id: str) -> dict:
    if challenge_id:
        challenge = _challenge_from_request(request, challenge_id)
        admin = challenge.admin
    else:
        admin = current_admin(request)
        if admin is None:
            raise DomainError("AUTH_REQUIRED", "需要登录", status_code=401)
        if admin.totp_secret_envelope:
            raise DomainError("TOTP_ALREADY_CONFIGURED", "验证器已绑定", status_code=409)
        if not recent_step_up_valid(request):
            raise DomainError(
                "STEP_UP_REQUIRED", "请重新验证身份", status_code=403, retryable=True
            )
        challenge = MFAChallenge.objects.create(
            admin=admin,
            kind="totp_setup",
            source_ip=request_ip(request),
            session_binding=_session_binding(request),
            expires_at=timezone.now() + timedelta(seconds=settings.MFA_CHALLENGE_SECONDS),
        )
        request.session["mfa_challenge_id"] = str(challenge.pk)
    if admin.totp_secret_envelope:
        raise DomainError("TOTP_ALREADY_CONFIGURED", "验证器已绑定", status_code=409)
    secret = pyotp.random_base32()
    envelope = configured_secret_store().encrypt(
        secret.encode(), purpose="control", aad=f"mfa-challenge:{challenge.pk}".encode()
    )
    request.session["pending_totp_envelope"] = envelope
    request.session.modified = True
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=challenge.admin.username, issuer_name="X-ray Manager"
    )
    return {
        "challenge_id": str(challenge.pk),
        "secret": secret,
        "otpauth_uri": uri,
        "expires_at": challenge.expires_at.isoformat(),
    }


def _secret_for_admin(admin: SuperAdmin) -> str:
    if not admin.totp_secret_envelope:
        raise DomainError("TOTP_SETUP_REQUIRED", "请先绑定验证器", status_code=409)
    return configured_secret_store().decrypt(
        admin.totp_secret_envelope, purpose="control", aad=f"totp:{admin.pk}".encode()
    ).decode()


def _verify_totp_for_admin(admin: SuperAdmin, code: str) -> int:
    totp = pyotp.TOTP(_secret_for_admin(admin))
    if not totp.verify(str(code), valid_window=0):
        raise DomainError("MFA_INVALID", "验证码错误", status_code=401)
    return totp.timecode(datetime.now(UTC))


def _verify_pending_totp(request, challenge: MFAChallenge, code: str) -> int:
    envelope = request.session.get("pending_totp_envelope")
    if not envelope:
        raise DomainError("TOTP_SETUP_REQUIRED", "请先获取绑定信息", status_code=409)
    secret = configured_secret_store().decrypt(
        envelope, purpose="control", aad=f"mfa-challenge:{challenge.pk}".encode()
    ).decode()
    totp = pyotp.TOTP(secret)
    if not totp.verify(str(code), valid_window=0):
        raise DomainError("MFA_INVALID", "验证码错误", status_code=401)
    return totp.timecode(datetime.now(UTC))


def _new_recovery_codes() -> list[str]:
    return [secrets.token_urlsafe(18) for _ in range(10)]


def _consume_recovery_code(admin: SuperAdmin, supplied: str) -> bool:
    for index, digest in enumerate(admin.recovery_code_hashes or []):
        if check_password(supplied, digest):
            remaining = list(admin.recovery_code_hashes)
            remaining.pop(index)
            admin.recovery_code_hashes = remaining
            admin.save(update_fields=["recovery_code_hashes", "updated_at"])
            return True
    return False


def _start_session(
    request,
    admin: SuperAdmin,
    challenge: MFAChallenge | None,
    *,
    recovery_codes: list[str] | None = None,
) -> dict:
    now = timezone.now()
    absolute = now + timedelta(seconds=settings.AUTH_SESSION_ABSOLUTE_SECONDS)
    request.session.cycle_key()
    request.session["admin_id"] = str(admin.pk)
    request.session["session_version"] = admin.session_version
    request.session["auth_at"] = now.isoformat()
    request.session["absolute_expires_at"] = absolute.isoformat()
    if challenge is None:
        request.session.pop("recent_auth_until", None)
    else:
        request.session["recent_auth_until"] = (
            now + timedelta(seconds=settings.AUTH_STEP_UP_SECONDS)
        ).isoformat()
    request.session.pop("mfa_challenge_id", None)
    request.session.pop("pending_totp_envelope", None)
    request.session.pop("xray_challenge_binding", None)
    request.session.set_expiry(settings.AUTH_SESSION_IDLE_SECONDS)
    if challenge is not None:
        challenge.used_at = now
        challenge.save(update_fields=["used_at"])
    AdminSession.objects.create(
        admin=admin,
        session_key_hash=hashlib.sha256(
            (request.session.session_key or "").encode()
        ).hexdigest(),
        expires_at=now + timedelta(seconds=settings.AUTH_SESSION_IDLE_SECONDS),
        absolute_expires_at=absolute,
        session_version=admin.session_version,
        last_step_up_at=now if challenge is not None else None,
        source_ip=request_ip(request),
        user_agent_hash=_user_agent_hash(request),
    )
    response = {
        "authenticated": True,
        "admin": {"username": admin.username},
        "expires_at": absolute.isoformat(),
        "mfa_required": False,
        "mfa_enabled": bool(admin.totp_secret_envelope),
        "totp_setup_required": False,
        "recent_auth_until": request.session.get("recent_auth_until"),
    }
    if recovery_codes is not None:
        response["recovery_codes"] = recovery_codes
    return response


def local_one_click_login(request) -> dict:
    if not local_one_click_login_enabled(request):
        raise DomainError(
            "LOCAL_LOGIN_UNAVAILABLE", "本地一键登录不可用", status_code=404
        )
    return _create_local_one_click_session(request)


@transaction.atomic
def _create_local_one_click_session(request) -> dict:
    try:
        admin = SuperAdmin.objects.select_for_update().get(is_active=True)
    except SuperAdmin.DoesNotExist as exc:
        raise DomainError("AUTH_UNAVAILABLE", "管理员账号不可用", status_code=503) from exc
    if admin.locked_until and admin.locked_until > timezone.now():
        raise DomainError("AUTH_UNAVAILABLE", "管理员账号暂不可用", status_code=503)
    return _start_session(request, admin, None)


@transaction.atomic
def complete_totp_setup(request, challenge_id: str, code: str) -> dict:
    challenge = _challenge_from_request(request, challenge_id)
    challenge = MFAChallenge.objects.select_for_update().select_related("admin").get(
        pk=challenge.pk
    )
    step = _verify_pending_totp(request, challenge, code)
    admin = SuperAdmin.objects.select_for_update().get(pk=challenge.admin_id)
    if admin.totp_secret_envelope:
        raise DomainError("TOTP_ALREADY_CONFIGURED", "验证器已绑定", status_code=409)
    pending = request.session["pending_totp_envelope"]
    secret = configured_secret_store().decrypt(
        pending, purpose="control", aad=f"mfa-challenge:{challenge.pk}".encode()
    )
    admin.totp_secret_envelope = configured_secret_store().encrypt(
        secret, purpose="control", aad=f"totp:{admin.pk}".encode()
    )
    admin.totp_confirmed_at = timezone.now()
    recovery_codes = _new_recovery_codes()
    admin.recovery_code_hashes = [make_password(code) for code in recovery_codes]
    admin.last_totp_step = step
    admin.save(
        update_fields=[
            "totp_secret_envelope",
            "totp_confirmed_at",
            "recovery_code_hashes",
            "last_totp_step",
            "updated_at",
        ]
    )
    revoke_all(admin)
    admin.refresh_from_db(fields=["session_version"])
    return _start_session(request, admin, challenge, recovery_codes=recovery_codes)


@transaction.atomic
def complete_totp(request, challenge_id: str, code: str) -> dict:
    challenge = _challenge_from_request(request, challenge_id)
    challenge = MFAChallenge.objects.select_for_update().select_related("admin").get(
        pk=challenge.pk
    )
    admin = SuperAdmin.objects.select_for_update().get(pk=challenge.admin_id)
    step = _verify_totp_for_admin(admin, code)
    if step <= admin.last_totp_step:
        raise DomainError("MFA_REPLAY", "验证码已使用", status_code=409)
    admin.last_totp_step = step
    admin.save(update_fields=["last_totp_step", "updated_at"])
    return _start_session(request, admin, challenge)


@transaction.atomic
def complete_recovery(request, challenge_id: str, code: str) -> dict:
    challenge = _challenge_from_request(request, challenge_id)
    challenge = MFAChallenge.objects.select_for_update().select_related("admin").get(
        pk=challenge.pk
    )
    admin = SuperAdmin.objects.select_for_update().get(pk=challenge.admin_id)
    if not _consume_recovery_code(admin, code):
        raise DomainError("RECOVERY_INVALID", "恢复码错误或已使用", status_code=401)
    return _start_session(request, admin, challenge)


def current_admin(request) -> SuperAdmin | None:
    admin_id = request.session.get("admin_id")
    if not admin_id:
        return None
    try:
        admin = SuperAdmin.objects.get(pk=admin_id, is_active=True)
    except SuperAdmin.DoesNotExist:
        return None
    if request.session.get("session_version") != admin.session_version:
        return None
    now = timezone.now()
    absolute = request.session.get("absolute_expires_at")
    if absolute:
        try:
            if now >= datetime.fromisoformat(absolute):
                return None
        except ValueError:
            return None
    return admin


def session_status(request) -> dict:
    admin = current_admin(request)
    if admin is None:
        pending_mfa = bool(request.session.get("mfa_challenge_id"))
        return {
            "authenticated": False,
            "mfa_required": pending_mfa,
            "mfa_enabled": pending_mfa,
            "expires_at": None,
            "recent_auth_until": None,
        }
    return {
        "authenticated": True,
        "mfa_required": False,
        "mfa_enabled": bool(admin.totp_secret_envelope),
        "admin": {"username": admin.username},
        "expires_at": request.session.get("absolute_expires_at"),
        "recent_auth_until": request.session.get("recent_auth_until"),
    }


def revoke_all(admin: SuperAdmin) -> None:
    now = timezone.now()
    SuperAdmin.objects.filter(pk=admin.pk).update(
        session_version=admin.session_version + 1, updated_at=now
    )
    AdminSession.objects.filter(admin=admin, revoked_at__isnull=True).update(revoked_at=now)
    MFAChallenge.objects.filter(admin=admin, used_at__isnull=True).update(used_at=now)


def recent_step_up_valid(request) -> bool:
    value = request.session.get("recent_auth_until")
    try:
        return bool(value and timezone.now() < datetime.fromisoformat(value))
    except (TypeError, ValueError):
        return False


def record_step_up(request, admin: SuperAdmin) -> datetime:
    now = timezone.now()
    until = now + timedelta(seconds=settings.AUTH_STEP_UP_SECONDS)
    request.session["recent_auth_until"] = until.isoformat()
    AdminSession.objects.filter(
        admin=admin,
        session_version=admin.session_version,
        session_key_hash=hashlib.sha256((request.session.session_key or "").encode()).hexdigest(),
        revoked_at__isnull=True,
    ).update(last_step_up_at=now)
    return until


def require_admin(view: Callable):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        admin = current_admin(request)
        if admin is None:
            return JsonResponse(
                {
                    "code": "AUTH_REQUIRED",
                    "message": "需要登录",
                    "retryable": False,
                    "operation_id": None,
                    "details": {},
                },
                status=401,
            )
        request.xray_admin = admin
        return view(request, *args, **kwargs)
    return wrapped


def require_recent_step_up(view: Callable):
    @wraps(view)
    @require_admin
    def wrapped(request, *args, **kwargs):
        if not recent_step_up_valid(request):
            return JsonResponse(
                {
                    "code": "STEP_UP_REQUIRED",
                    "message": "请重新验证身份",
                    "retryable": True,
                    "operation_id": None,
                    "details": {},
                },
                status=403,
            )
        return view(request, *args, **kwargs)

    return wrapped
