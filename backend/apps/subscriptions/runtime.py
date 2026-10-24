"""Read-only deployment checks. Never connect to nodes or consume operations."""

from django.conf import settings
from django.utils.module_loading import import_string


def subscription_runtime():
    checks = {}
    for name, setting in (
        ("access_transport", "XRAY_NODE_TRANSPORT_FACTORY"),
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
    checks["revocation_executor"] = "unconfigured"
    checks["worker"] = "unverified"
    checks["scheduler"] = "unverified"
    return {
        "status": "incomplete",
        "checks": checks,
        "node_connections_attempted": False,
        "operations_dispatched": False,
    }
