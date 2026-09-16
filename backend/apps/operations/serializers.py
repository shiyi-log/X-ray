from __future__ import annotations


def step_representation(step) -> dict:
    return {
        "id": step.pk,
        "name": step.name,
        "phase": step.phase,
        "status": step.status,
        "attempt": step.attempt,
        "external_request_id": step.external_request_id,
        "result": step.result,
        "evidence": step.evidence,
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "finished_at": step.finished_at.isoformat() if step.finished_at else None,
    }


def operation_representation(operation, *, include_steps: bool = False) -> dict:
    value = {
        "id": str(operation.pk),
        "kind": operation.kind,
        "target_type": operation.target_type,
        "target_id": str(operation.target_id),
        "status": operation.status,
        "current_step": operation.current_step,
        "can_cancel": operation.can_cancel,
        "error_code": operation.error_code,
        "error_details": operation.error_details,
        "result": operation.result,
        "created_at": operation.created_at.isoformat(),
        "updated_at": operation.updated_at.isoformat(),
    }
    if operation.kind == "subscription.revoke":
        value["link_revoked"] = True
    if include_steps:
        value["steps"] = [step_representation(step) for step in operation.steps.all()]
        value["revocation_nodes"] = [
            {
                "node_id": str(state.node_id),
                "status": state.status,
                "target_generation": state.target_generation,
                "last_error_code": state.last_error_code,
                "evidence": state.evidence,
            }
            for state in operation.revocation_nodes.select_related("node").all()
        ]
    return value


def preview_representation(preview) -> dict:
    return {
        "id": str(preview.pk),
        "kind": preview.kind,
        "target_id": str(preview.target_id),
        "snapshot": preview.snapshot,
        "required_phrase": preview.required_phrase,
        "expires_at": preview.expires_at.isoformat(),
    }
