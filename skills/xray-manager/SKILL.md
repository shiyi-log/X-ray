---
name: xray-manager
description: Maintain the isolated X-ray management platform and its auditable delivery workflow.
---

# X-ray Manager

Use this skill for work under `/Users/a399/Desktop/data/X-ray`.

## Non-negotiable boundaries

- Keep the project independent from Shop and sibling repositories. `archive/` is local reference data only and must never enter source discovery, Docker contexts, packages, CI artifacts, or tests.
- Use the dedicated PostgreSQL/Redis stack and fake or stub cloud/SSH providers for local verification. Real AWS, SWAS, SSH, public probes, production hosts, deletion, and IP release require explicit authorization.
- Never print or persist private keys, cloud credentials, subscription tokens, raw URI payloads, or secret-bearing exception data. Use purpose-bound AEAD envelopes and redact logs/reports.

## Delivery workflow

1. Inspect branch, status, listeners, dependency versions, current progress, and the applicable phase plan before editing.
2. Implement a failing focused test, make the smallest compatible change, then run focused and regression gates.
3. Record command, exit code, evidence path, status (`passed`, `failed`, `blocked`, `not-run`, or `risky_not_executed`), commit, tag, and rollback reference in `docs/progress.md`.
4. Update `VERSION`, `CHANGELOG.md`, and `docs/version-record.md` for each phase. Review staged paths and use a phase tag or `git revert` for rollback; never force-push or hard-reset.

## Domain invariants

- There is one database-enforced administrator. Password login creates only a short-lived MFA challenge; a current server-side session and session version authorize management APIs.
- Side-effecting APIs require a UUID `Idempotency-Key`; dangerous actions require a fresh, target-bound preview and step-up authentication.
- Cloud capability is evidence-based (`SUPPORTED`, `UNSUPPORTED`, `UNVERIFIED`). Accepted cloud writes are not treated as completed until read-after-write evidence exists.
- Subscription access is token-digest based and fail-closed. A revoked token is permanently `410`; uncertain node revocation is visible as risk and never claimed successful.
- Recovery starts in `MAINTENANCE`: public subscriptions are unavailable and workers cannot perform cloud writes until audit/revocation reconciliation and credential rotation are verified.

## References

- Read [architecture.md](references/architecture.md) for module boundaries and shared interfaces.
- Read [acceptance.md](references/acceptance.md) for status vocabulary and local/external evidence rules.
- Read [versioning-and-recovery.md](references/versioning-and-recovery.md) for commits, tags, backups, and rollback safety.
