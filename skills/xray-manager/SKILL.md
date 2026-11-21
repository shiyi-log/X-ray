---
name: xray-manager
description: Maintain the X-ray source fork based on pinned MHSanaei/3x-ui with audited local verification.
---

# X-ray Manager

The active application is the GPLv3 source baseline in `UPSTREAM.json`. Its exact imported files are hash-listed in `artifacts/acceptance/3x-ui-rebase-20261117/replacement-manifest.json`. The canonical working contract is [../../docs/project-conventions.md](../../docs/project-conventions.md); the append-only operation record is [../../docs/project-ledger.md](../../docs/project-ledger.md).

## Before editing

1. Read `AGENTS.md`, the canonical conventions, ledger, relevant current progress, and affected source. Do not use obsolete Django/Vben instructions as active commands.
2. Inspect branch/status/diff, toolchain versions, baseline hashes, relevant processes/listeners, port registrations, and ignored state without printing secrets.
3. Append a task definition with goal, scope, exclusions, authorization, assumptions, risk, time rules, and rollback. Preserve all pre-existing dirty/untracked files and application data.
4. For the untouched base run `python3 scripts/check-baseline.py`. A future customization must first introduce an explicit reviewed patch policy; do not regenerate a digest to silence a baseline mismatch.

## Execution and evidence

- Keep upstream license, copyright, locked dependencies, and source provenance. Do not import `archive/`, sibling Shop projects, local environments, old DBs, or generated runtime state.
- New behavior follows test-first development with a test that exercises the real code path. Keep the upstream diff small and auditable.
- The upstream first-run path prints default panel credentials. Until a separately reviewed bootstrap/secret-delivery change exists, do not initialize or launch the panel or upstream installer.
- Local verification uses fresh temporary SQLite state. Do not connect the old PostgreSQL/Redis stacks by default. Go/Browser tests may bind temporary ports; run them in isolated containers without host port publishing, never on host networking. If a hosted listener is needed later, use the shared port manager and inspect ownership before starting it.
- `bash scripts/check-local.sh` is the source gate: baseline, locked npm install, frontend lint/format/typecheck/full tests/build, Go module verification, Go tests, vet, and actual binary build. CI is source-only with read permission and does not deploy or publish.
- Record exact exit code, package/test counts, skip reasons, tool versions, container/image identity, and evidence path. A successful compile is not proof of UI login, Xray traffic, node operation, cloud capability, or production availability. Preserve `not-run`, `blocked`, `failed`, and `risky_not_executed` honestly.
- Never expose credentials, raw URI, cookie, access token, secret exception, or unredacted process output in project evidence. Store full test logs only in an access-restricted temporary directory, not tracked artifacts.

## X-ray boundaries

- Historical Django features such as Lightsail allocation, sensitive-action step-up, append-only security state, revocation tombstones, restore barriers, subscription pools, and online upgrade are not assumed to exist in upstream 3x-ui. Make no such claim until separately implemented and verified.
- AWS is Lightsail-only; do not create EC2. Real cloud writes, SSH, public probes, deletion, IP release, real device testing, TLS and production publication need task-specific authorization.
- No database migration or live panel start is included in a baseline build. Do not restore old database, revoked tokens, credentials, security events, or cloud state.

## Finish

Run `git diff --check`, source and boundary checks, a redacted secret scan, and final status review. Append a final verification ledger entry and current gate evidence to `docs/progress.md`; retain historical version/matrix records without rewriting their meaning. State remaining limitations, exact files and rollback commit `ad90a0f4c5d58adab703ecfe25bf268321f5e44a`. Do not create a version/tag/release unless the task explicitly requests a release.
