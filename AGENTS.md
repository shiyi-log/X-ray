# X-ray Repository Rules

## Scope and boundaries

- This repository is an independent X-ray manager. Do not import, copy, execute, or read runtime secrets from Shop, `vue-shop-admin`, `shop-xray-installer`, or `archive/`.
- Preserve unrelated processes, ports, credentials, databases, and dirty files. Inspect listeners before starting services; never stop another project to claim a port.
- Real AWS/SWAS, SSH, Google probes, production servers, instance deletion, and IP release require explicit task-specific authorization. Local tests use fake/stub providers and dedicated PostgreSQL/Redis only.

## Implementation rules

- Use `skills/xray-manager/SKILL.md` and the linked references for project-specific decisions.
- Keep public interfaces and migration compatibility stable. Secrets are transient, purpose-bound, encrypted, and never placed in logs, URLs, localStorage, command arguments, or reports.
- Every side-effecting API uses a UUID `Idempotency-Key`; dangerous actions require a fresh preview and step-up authentication.
- Record each meaningful command, exit code, evidence path, status, commit, and rollback reference in `docs/progress.md`.

## Git and release

- Work on `codex/xray-manager`; do not rewrite `main`.
- Stage only the coherent phase change. Run `git diff --check`, focused tests, boundary/secret scans, and review staged paths before committing.
- Update `VERSION`, `CHANGELOG.md`, and `docs/version-record.md` with every phase tag. Use `git revert` or a phase tag for rollback.
