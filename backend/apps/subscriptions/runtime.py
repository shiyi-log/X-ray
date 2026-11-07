"""Read-only deployment checks. Never connect to nodes or consume operations."""

from django.conf import settings
from django.utils.module_loading import import_string


def subscription_runtime():
    checks = {}
    for name, setting in (
        ("access_transport", "XRAY_NODE_TRANSPORT_FACTORY"),
        ("node_health_probe", "XRAY_NODE_HEALTH_PROBE"),
        ("usage_collector", "XRAY_USAGE_FETCHER"),
    ):
        path = getattr(settings, setting, "")
        if not path:
            checks[name] = "unconfigured"
            continue
        try:
            checks[name] = "configured" if callable(import_string(path)) else "invalid"
        except Exception:
            # Import exceptions can contain configuration or credentials.
            checks[name] = "invalid"
    from .revocation_runtime import SUPPORTED_REVOCATION

    checks["revocation_executor"] = (
        "configured_subset" if checks["access_transport"] == "configured" else "unconfigured"
    )
    checks["worker"] = "unverified"
    checks["scheduler"] = "unverified"
    return {
        "status": "incomplete",
        "checks": checks,
        "revocation_support": dict(SUPPORTED_REVOCATION),
        "node_connections_attempted": False,
        "operations_dispatched": False,
    }
