from uuid import uuid4

import pytest

from apps.nodes.execution_types import IsolationResult
from common.errors import DomainError

from .test_revocation import make_preview


class FailingExecutor:
    def capture_probe_sessions(self, *args, **kwargs):
        raise DomainError("SSH_UNAVAILABLE", "ssh unavailable", status_code=503)


class IsolationLifecycle:
    def __init__(self, confirmed):
        self.confirmed = confirmed

    def quarantine(self, node_id, *, operation_id):
        return IsolationResult(
            self.confirmed,
            {"firewall_safe": self.confirmed, "data_plane": {"complete": self.confirmed}},
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("confirmed", "expected"),
    [(True, "QUARANTINED"), (False, "REVOCATION_UNCONFIRMED")],
)
def test_failed_precise_revocation_records_isolation_without_claiming_success(
    admin, revocable_profile, confirmed, expected
):
    from apps.subscriptions.models import RevocationNodeState
    from apps.subscriptions.revocation import RevocationService

    _issued, profile, node, _credential = revocable_profile
    preview = make_preview(admin, profile)
    operation = RevocationService.request(
        profile.pk,
        key=uuid4(),
        preview_id=preview.pk,
        confirmation="REVOKE PROFILE",
        admin=admin,
        test_only_skip_runtime_preflight=True,
    )
    invalidated = []
    service = RevocationService(
        executor_factory=lambda _node: FailingExecutor(),
        lifecycle_factory=lambda: IsolationLifecycle(confirmed),
        invalidate_node=lambda node_id: invalidated.append(node_id),
    )
    service.run(operation.pk)

    profile.refresh_from_db()
    operation.refresh_from_db()
    node.refresh_from_db()
    state = RevocationNodeState.objects.get(operation=operation, node=node)
    assert invalidated == [node.pk]
    assert state.status == expected
    assert profile.status == "REVOKING"
    assert operation.status == "PARTIALLY_SUCCEEDED"
    assert node.security_state == (
        "QUARANTINED" if confirmed else "REVOCATION_UNCONFIRMED"
    )


def test_node_outcomes_do_not_equate_quarantine_with_precise_removal():
    from apps.subscriptions.verification import choose_node_outcome

    assert choose_node_outcome(removed=True, isolation_confirmed=False) == "VERIFIED_REVOKED"
    assert choose_node_outcome(removed=False, isolation_confirmed=True) == "QUARANTINED"
    assert (
        choose_node_outcome(removed=False, isolation_confirmed=False)
        == "REVOCATION_UNCONFIRMED"
    )
