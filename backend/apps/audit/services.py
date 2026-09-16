from .models import AuditEvent


_SECRET_KEYS = {
    "password",
    "passwd",
    "token",
    "secret",
    "private_key",
    "privatekey",
    "credential",
    "credentials",
    "authorization",
    "cookie",
    "wrapped_dek",
    "ciphertext",
}


def _sanitize(value):
    if isinstance(value, dict):
        return {
            str(k): (
                "[REDACTED]"
                if str(k).lower() in _SECRET_KEYS
                or any(secret in str(k).lower() for secret in _SECRET_KEYS)
                else _sanitize(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    return value


class AuditService:
    @staticmethod
    def append(*, action, target_type, target_id="", result, metadata=None, actor=None, request_id=""):
        return AuditEvent.objects.create(
            action=action,
            target_type=target_type,
            target_id=str(target_id or ""),
            result=result,
            metadata=_sanitize(metadata or {}),
            actor=actor,
            request_id=request_id or "",
        )
