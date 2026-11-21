# Versioning and Recovery

The current application source is pinned by `UPSTREAM.json` and the file SHA manifest. Root `VERSION`, `CHANGELOG.md`, `docs/version-record.md`, and `tests/acceptance/matrix.json` retain the prior Django application history; `0.14.12` is not the 3x-ui base version.

This base replacement is not a release: do not create a version, tag, commit, GitHub Release, registry image, installer, or deployment unless a separate task explicitly requests that outcome and all required source/license/build review is complete. CI stays read-only and does not publish.

Rollback to the prior source tree is anchored at `ad90a0f4c5d58adab703ecfe25bf268321f5e44a`. Use a reviewed exact diff or `git revert` if the work is committed; never hard reset or clean a shared workspace. The current run's pre-existing worktree patch and tracked-file hashes are in the private `~/.codex/tmp/xray-3xui-rebase-20261117/` snapshot. Preserve those user changes and all untracked acceptance artifacts.

Do not reuse the old database, credentials, revoked subscription tokens, session/security history, cloud-operation history, or old production images as 3x-ui state. No database migration has been designed or run. An upstream compile or test does not make a legacy backup restorable.

Future upstream syncs must pin a tag and commit, verify the source archive hash, review all changed paths/licenses/workflows, generate a new imported-file manifest, run applicable gates, record exact evidence, and describe rollback before changing the baseline.
