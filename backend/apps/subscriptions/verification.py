from __future__ import annotations

from apps.nodes.execution_types import ProbeResult


def verified_revoked(result: ProbeResult) -> bool:
    return bool(
        result.accepted is False
        and result.positive_control is True
        and result.fresh_connection is True
        and result.existing_session_closed is True
    )


def choose_node_outcome(*, removed: bool, isolation_confirmed: bool) -> str:
    if removed:
        return "VERIFIED_REVOKED"
    if isolation_confirmed:
        return "QUARANTINED"
    return "REVOCATION_UNCONFIRMED"
