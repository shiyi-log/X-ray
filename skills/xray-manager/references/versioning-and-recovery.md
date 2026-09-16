# Versioning and Recovery Reference

Every phase has a focused commit and annotated tag. Update `VERSION`, `CHANGELOG.md`, `docs/version-record.md`, and `docs/progress.md` in the same coherent change. Review `git diff --cached --stat` and `git diff --cached --check` before committing.

Application rollback uses a phase tag or `git revert`; do not reset shared history. Deployment rollback changes only the verified image and never resurrects revoked tokens, credentials, or cloud actions. Database changes use expand/contract compatibility. A restored system starts in `MAINTENANCE`; subscriptions return 503, cloud writes are blocked, Redis/outbox state is rebuilt, and security audit/revocation reconciliation plus credential rotation must complete before manual reopening.

Before the delivery tag, record immutable backend, frontend, and backup-tools
image digests plus the encrypted restore receipt. The release checklist is
`docs/release-checklist.md`; a completed local checklist is not production
acceptance while the production matrix row remains blocked.
