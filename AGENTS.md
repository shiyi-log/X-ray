# X-ray Repository Instructions

The active application is a source-based fork of [MHSanaei/3x-ui](https://github.com/MHSanaei/3x-ui), pinned at `v3.11.0` commit `c621ba9014a6aa21fd7c9ecf45655e44e24ebf13`. `UPSTREAM.json` and `artifacts/acceptance/3x-ui-rebase-20261117/replacement-manifest.json` hold the immutable source identity and file hashes. Read [docs/project-conventions.md](docs/project-conventions.md), [docs/project-ledger.md](docs/project-ledger.md), and [skills/xray-manager/SKILL.md](skills/xray-manager/SKILL.md) before changes.

## Hard boundaries

- Do not read, import, copy, execute, build, or package `archive/`, Shop, `vue-shop-admin`, or `shop-xray-installer`. They are outside this application.
- Preserve user worktree changes, untracked acceptance artifacts, ignored dependencies, processes, listeners, ports, databases, credentials, and browser sessions. Inspect ownership before any runtime action.
- Local database tests use new disposable SQLite databases unless a task specifically approves a dedicated test PostgreSQL setup. Never reuse the old X-ray PostgreSQL/Redis stacks or old application databases.
- Real AWS/SWAS writes, SSH, public probes, production hosts, deletion, static-IP release, and production publication require explicit task-specific authorization. Any future AWS work must use Lightsail, never EC2.
- Never expose or persist passwords, private keys, cloud credentials, panel/session/subscription tokens, raw client URIs, cookies, or secret-bearing exception text in source, arguments, logs, URLs, storage, screenshots, reports, or ledgers.
- Do not run the upstream installer, initialize a panel, or launch Xray for a build check. Upstream first-run credentials are printed to the terminal and have not yet been adapted to this project's secret-delivery requirements.
- CI is source-only with `contents: read`; keep deployment, release, registry publication, SSH, and real-service workflows disabled.

## Mandatory work contract

1. Read current instructions, conventions, ledger, status/diff, relevant implementation, and toolchain before editing.
2. Define goal, scope, exclusions, assumptions, authorization, risks, and rollback in the append-only ledger.
3. Keep the pinned upstream byte-for-byte until a separately scoped customization is approved. Before the first customization, replace the import-only baseline gate with an explicit reviewable patch/source policy.
4. For behavior changes, add a focused test first. For process/documentation changes, run static validators, source-boundary and secret checks.
5. Record reads, writes, commands, exact exit codes, skips, limitations, license/source changes, and rollback in `docs/project-ledger.md`. Record current gate outcomes in `docs/progress.md`; retain old version/release records as history.
6. Verify with `git diff --check`, the focused test, source/baseline check, lockfile verification, and secret scan. A passing Go or frontend suite does not prove database migration, Xray traffic, browser acceptance, or production.
7. Before finishing, inspect `git status --short --branch`, append the final verification event, state unrun/blocked gates, and give exact files/evidence.

## Git and rollback

- Work directly on the user's current branch, currently `main`. Do not create/switch branches, force-push, hard-reset, or clean untracked files.
- Stage only the requested coherent change. Exclude environments, databases, credentials, browser state, runtime artifacts, and unrelated dirty files.
- This base replacement creates no project version, tag, release, or deployment. Root `VERSION`, `CHANGELOG.md`, `docs/version-record.md`, and `tests/acceptance/matrix.json` describe the legacy system unless a later release explicitly updates them.
- Legacy implementation rollback reference is commit `ad90a0f4c5d58adab703ecfe25bf268321f5e44a`; do not restore its data stores, revoked tokens, credentials, security events, or cloud-operation state.
