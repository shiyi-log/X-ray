# X-ray Repository Instructions

This file is the repository-level entry point for coding agents. The complete
project contract is [docs/project-conventions.md](docs/project-conventions.md).
The operation-level audit trail is [docs/project-ledger.md](docs/project-ledger.md).
The X-ray-specific execution skill is [skills/xray-manager/SKILL.md](skills/xray-manager/SKILL.md).

## Hard Boundaries

- This is an independent X-ray manager. Do not import, copy, execute, or read
  runtime secrets from Shop, `vue-shop-admin`, `shop-xray-installer`, or
  `archive/`. Those paths are read-only reference boundaries and are not runtime
  inputs.
- Preserve unrelated worktree changes, processes, ports, credentials, databases,
  and browser sessions. Inspect ownership before starting or stopping anything.
- Real AWS/SWAS writes, SSH, public probes, production hosts, deletion, static-IP
  release, and production publication require explicit task-specific
  authorization. Local verification uses only the dedicated PostgreSQL/Redis
  stack and Fake/Stub providers.
- Never expose or persist passwords, private keys, cloud credentials,
  subscription tokens, raw URI payloads, cookies, or secret-bearing exception
  text in source, arguments, logs, URLs, localStorage, screenshots, reports, or
  ledgers.

## Mandatory Work Contract

1. Read the applicable instructions, canonical project conventions, ledger,
   current status/diff, and relevant implementation files before writing.
2. Define the requested outcome, in-scope and out-of-scope files, assumptions,
   authorization boundary, risks, and rollback path in the ledger.
3. Make the smallest compatible change. For code behavior, add or update a
   focused test; for documentation/process changes, run the applicable static
   validators and boundary checks.
4. Record every meaningful read, write, time rule, command, test, decision,
   limitation, reuse path, and rollback path in `docs/project-ledger.md`.
5. Record phase/gate evidence, exact exit codes, acceptance status, commit/tag,
   and rollback reference in `docs/progress.md`. Use
   `docs/version-record.md` only for version/tag/migration/release indexing.
6. Verify proportionally: `git diff --check`, focused tests, boundary/secret
   scans, and the relevant local/runtime/browser gates. Never convert
   not-run, blocked, Fake/Stub, or container evidence into production success.
7. Before finishing, inspect `git status`, append the final verification event,
   state unresolved limits, and give the user the exact files and evidence.

## Git and Release

- Work directly on the user's current branch (currently `main`); do not switch or
  create a work branch unless the user explicitly requests branch operations.
  Do not force-push or hard-reset.
- Stage only the coherent requested change. Do not include `.env`, keys,
  databases, wallets, credentials, browser state, generated secrets, or
  unrelated dirty files.
- A phase release updates `VERSION`, `CHANGELOG.md`, `docs/version-record.md`,
  and `docs/progress.md`, then uses an annotated tag and an explicit rollback
  reference. A documentation/process rewrite without a phase release does not
  invent a new version or tag.
- Roll back application code with a phase tag or `git revert`; database recovery
  is expand/contract and must never resurrect revoked tokens, credentials,
  security events, or cloud-operation state.
