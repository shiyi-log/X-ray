import io
import json
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.subscriptions.runtime import subscription_runtime


@override_settings(
    XRAY_NODE_TRANSPORT_FACTORY="",
    XRAY_NODE_HEALTH_PROBE="",
    XRAY_USAGE_FETCHER="",
)
def test_missing_runtime_is_explicit_without_network_or_dispatch():
    with patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
        result = subscription_runtime()
    assert result["checks"]["access_transport"] == "unconfigured"
    assert result["checks"]["node_health_probe"] == "unconfigured"
    assert result["checks"]["usage_collector"] == "unconfigured"
    assert result["checks"]["worker"] == "unverified"
    assert result["status"] == "incomplete"
    assert result["node_connections_attempted"] is False
    assert result["operations_dispatched"] is False


@override_settings(
    XRAY_NODE_TRANSPORT_FACTORY="apps.subscriptions.node_agent.aws_transport",
    XRAY_NODE_HEALTH_PROBE="apps.subscriptions.node_agent.fetch_usage",
    XRAY_USAGE_FETCHER="apps.subscriptions.node_agent.fetch_usage",
)
def test_importable_adapters_do_not_claim_live_readiness():
    result = subscription_runtime()
    assert result["checks"]["access_transport"] == "configured"
    assert result["checks"]["node_health_probe"] == "configured"
    assert result["checks"]["usage_collector"] == "configured"
    assert result["checks"]["revocation_executor"] == "unconfigured"
    assert result["status"] == "incomplete"


def test_invalid_import_does_not_disclose_exception():
    with patch(
        "apps.subscriptions.runtime.import_string", side_effect=RuntimeError("secret-fixture")
    ):
        with override_settings(
            XRAY_NODE_TRANSPORT_FACTORY="invalid.path",
            XRAY_NODE_HEALTH_PROBE="",
            XRAY_USAGE_FETCHER="",
        ):
            result = subscription_runtime()
    assert result["checks"]["access_transport"] == "invalid"
    assert "secret-fixture" not in json.dumps(result)


def test_strict_command_fails_closed_and_outputs_safe_json():
    output = io.StringIO()
    with pytest.raises(CommandError, match="SUBSCRIPTION_RUNTIME_INCOMPLETE"):
        call_command("check_subscription_runtime", strict=True, stdout=output)
    assert json.loads(output.getvalue())["status"] == "incomplete"
