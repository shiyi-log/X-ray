from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IsolationResult:
    confirmed: bool
    evidence: dict


@dataclass(frozen=True, slots=True)
class ApplyResult:
    applied_generation: int
    config_test_passed: bool
    service_restarted: bool
    rollback_performed: bool


@dataclass(frozen=True, slots=True)
class ProbeResult:
    accepted: bool | None
    positive_control: bool
    fresh_connection: bool
    existing_session_closed: bool | None
    evidence: dict
