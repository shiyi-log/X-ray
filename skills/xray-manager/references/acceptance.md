# Acceptance Reference

Use only these statuses: `passed`, `failed`, `blocked`, `not-run`, `risky_not_executed`.

`passed` requires reproducible command output and an evidence path. Fake/Stub, documentation, sandbox, and real-cloud evidence are separate dimensions. A local mock pass never proves production availability. Any real-cloud row marked `passed` must include authorization reference, complete operation ID, provider request ID, redacted resource identity, timestamp, and probe evidence.

Local gates include Django checks/migrations, PostgreSQL concurrency tests, provider stubs, installer validation, subscription parser tests, Playwright, frontend typecheck/lint/build, Compose/image boundary, secret scan, and recovery tests. Public Google probes, real SSH, AWS/SWAS writes, production TLS, deletion and IP release remain unexecuted unless explicitly authorized.
