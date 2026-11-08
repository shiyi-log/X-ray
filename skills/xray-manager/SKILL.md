---
name: xray-manager
description: Maintain the isolated X-ray management platform and its auditable delivery workflow.
---

# X-ray Manager

Use this skill for work under `/Users/a399/Desktop/data/X-ray`. The canonical
project contract is [../../docs/project-conventions.md](../../docs/project-conventions.md);
the append-only operation record is [../../docs/project-ledger.md](../../docs/project-ledger.md).

## Required Start

Before any edit:

1. Read `AGENTS.md`, `docs/project-conventions.md`,
   `docs/project-ledger.md`, and the relevant linked reference files.
2. Inspect branch, status, diff, listeners, dependency versions, current
   progress, and the applicable plan.
3. Create or reuse a `run_id`; append a ledger definition entry containing
   scope, exclusions, authorization, assumptions, risks, and rollback.

Do not read `archive/` or sibling Shop runtime material. Do not print ignored
environment files or secret-bearing output; record only redacted metadata.

## Execution

1. Read before writing and record exact paths and scopes.
2. Make the smallest compatible implementation. Code changes need a focused
   test; documentation/process changes need the relevant validator and boundary
   checks.
3. Treat time as an explicit contract: authoritative clock, IANA timezone,
   aware/naive parsing, UTC normalization, boundary convention, TTL/expiry,
   retries, clock skew, DST/offset behavior, and boundary test vectors.
4. Record each write, command, test, browser/runtime check, external limitation,
   reuse path, and rollback path in `docs/project-ledger.md`.
5. Record phase/gate evidence in `docs/progress.md`; record release/version/tag
   facts in `docs/version-record.md`. Do not claim a phase release for a
   process-only document change.
6. Run proportional verification and classify every result honestly:
   `passed`, `failed`, `blocked`, `not-run`, or `risky_not_executed`.
7. Append a final ledger event after `git diff --check`, status inspection, and
   relevant validators. Corrections append new events; they do not rewrite
   history.

## X-ray Safety Invariants

- PostgreSQL is the source of truth; Redis/Celery work is reconstructible.
- There is one database-enforced administrator. TOTP enrollment is optional and
  initiated by the administrator after authenticated, recent step-up. Normal
  password login starts a session when TOTP is unbound; a bound administrator
  must complete TOTP or a one-time recovery code. Explicit local test login
  bypasses remain unavailable in production.
- Server-side sessions, CSRF, session-version invalidation, TOTP/recovery,
  purpose-separated AEAD envelopes, and secret redaction remain mandatory.
- Sensitive actions still require recent step-up: password when TOTP is unbound,
  password plus TOTP when bound. Ordinary password login grants no recent
  step-up. Password or TOTP recovery invalidates old sessions and unused
  authentication challenges; enrollment secrets and recovery codes stay in page
  memory only.
- Every side-effecting API requires a UUID `Idempotency-Key`. Dangerous actions
  require a fresh target-bound preview and step-up authentication.
- Cloud capability is evidence-based: `SUPPORTED`, `UNSUPPORTED`, or
  `UNVERIFIED`. Accepted cloud writes require read-after-write evidence.
- Subscription access is token-digest based and fail-closed. Revoked tokens
  remain permanently `410`; uncertain node revocation is visible as risk.
- Recovery starts in `MAINTENANCE`; public subscriptions and cloud writes stay
  blocked until audit/revocation reconciliation and credential rotation pass.

## Local Evidence Boundary

Use the dedicated PostgreSQL/Redis Compose stack and Fake/Stub cloud/SSH
providers. Real AWS/SWAS, SSH, public Google probes, production TLS, production
hosts, deletion, static-IP release, and device acceptance are separate external
gates and remain `blocked`, `not-run`, or `risky_not_executed` without explicit
authorization and evidence.

## References

- [Project conventions](../../docs/project-conventions.md)
- [Project ledger](../../docs/project-ledger.md)
- [Architecture](references/architecture.md)
- [Acceptance](references/acceptance.md)
- [Versioning and recovery](references/versioning-and-recovery.md)
