# Acceptance Reference

Use only these statuses: `passed`, `failed`, `blocked`, `not-run`, `risky_not_executed`.

`passed` requires reproducible command output and an evidence path. Fake/Stub, documentation, sandbox, and real-cloud evidence are separate dimensions. A local mock pass never proves production availability. Any real-cloud row marked `passed` must include authorization reference, complete operation ID, provider request ID, redacted resource identity, timestamp, and probe evidence.

Local gates include Django checks/migrations, PostgreSQL concurrency tests, provider stubs, installer validation, subscription parser tests, Playwright, frontend typecheck/lint/build, Compose/image boundary, secret scan, and recovery tests. Public Google probes, real SSH, AWS/SWAS writes, production TLS, deletion and IP release remain unexecuted unless explicitly authorized.

Run `./scripts/check-local.sh` for the ordered local gate and
`python3 scripts/validate-acceptance.py` for ledger-only validation. Evidence
belongs under `artifacts/acceptance/<version>/`; it must be redacted and must
not contain raw tokens, cookies, private keys, environment files, or database
dumps. Use `docs/cloud-test-authorization.md` before any external write.

For P3 and later, the fixed-runtime gate must set `XRAY_REQUIRE_FIXED_BINARY=1` and point `XRAY_TEST_BINARY` at an archive-hash-verified binary produced by `scripts/fetch-xray-test-asset.sh`. A skipped runtime test is `not-run`, never `passed`.
