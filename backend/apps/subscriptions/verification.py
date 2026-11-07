from __future__ import annotations

from apps.nodes.execution_types import ProbeResult


def verified_revoked(result: ProbeResult) -> bool:
    common = (
        result.positive_control is True
        and result.fresh_connection is True
        and result.existing_session_closed is True
    )
    if result.accepted is False:
        return common
    if result.accepted is not None:
        return False
    evidence = result.evidence
    return bool(
        common
        and evidence.get("credential_excluded") is True
        and evidence.get("expected_config_applied") is True
        and evidence.get("service_restarted") is True
        and evidence.get("process_identity_changed") is True
        and evidence.get("credential_config_hash_matches") is True
        and evidence.get("preapply_credentials_accepted") is True
        and evidence.get("postapply_control_accepted") is True
    )


def choose_node_outcome(*, removed: bool, isolation_confirmed: bool) -> str:
    if removed:
        return "VERIFIED_REVOKED"
    if isolation_confirmed:
        return "QUARANTINED"
    return "REVOCATION_UNCONFIRMED"
