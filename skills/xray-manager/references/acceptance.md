# Acceptance Reference

Use only `passed`, `failed`, `blocked`, `not-run`, and `risky_not_executed`. A pass requires a reproducible command, exact exit code, current source identity, and evidence path.

## Source baseline

For imported upstream files, run `python3 scripts/check-baseline.py`. It checks each pinned hash, retired legacy paths, CI workflow boundary, and the Docker context allowlist. A future customization must replace the byte-for-byte import check with an explicit reviewed patch policy before code is edited.

The local source gate is `bash scripts/check-local.sh`. It installs locked npm dependencies with `HUSKY=0`, runs frontend lint, format, types, Vitest unit/component/Storybook projects, builds the real frontend, verifies Go modules, runs all Go tests with shuffle/count=1, runs vet, and builds the full embedded panel. Record skip conditions printed by Go tests.

CI is configured in `.github/workflows/ci.yml`, uses only `contents: read`, and has no registry, release, SSH, cloud, or deployment writes. An untriggered CI workflow is not accepted evidence for a local run.

Tests that bind random ports run in an isolated container without published host ports or host network. Tests use new disposable SQLite. PostgreSQL-backed integration, Xray process/gRPC, master/node process, scale, and browser behavior beyond Storybook remain distinct gates. Never reuse the legacy PG/Redis stack or database.

## External and runtime gates

Only an actual authorized runtime test can verify login, first-run admin delivery, database migration, Xray data plane, TLS, node sync, public subscriptions, AWS behavior, production availability, or resource costs. These are `not-run` for a source build. Real AWS/SWAS, SSH, public probe, production, deletion, IP release, device acceptance, and publication remain blocked without new task-specific authorization. AWS choices are Lightsail-only; do not use EC2.

Logs may contain credentials or raw client links. Keep full logs in a private temporary directory; project evidence must be redacted and limited to safe summaries.
