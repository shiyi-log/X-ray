# SDD ledger - plan: docs/superpowers/plans/2026-09-16-xray-p1-foundation.md

## Pre-flight scan

| Task | Shared files/interfaces | Finding | Ruling |
| --- | --- | --- | --- |
| P1.1 / P1.2 | `backend/config/settings/base.py`, `backend/tests/conftest.py`, Django settings | P1.1 must establish settings and test bootstrap; P1.2 adds `AUTH_USER_MODEL` and database models. | P1.1 provides importable settings and test fixtures without locking the auth model; P1.2 owns the first identity migration and updates settings before migration generation. |
| P1.1 / P1.3 | `backend/config/urls.py`, settings, auth test client | P1.1 needs health and empty subscription URL boundaries; P1.3 later adds auth routes and production cookie settings. | P1.1 keeps auth routes absent and exposes only health; P1.3 extends the URL tree and hardens production settings. |
| P1.2 / P1.3 | identity model, migrations, session version, audit service | Session/MFA depends on the singleton admin and audit primitives. | P1.2 owns model/crypto/audit contracts; P1.3 consumes them and adds authentication state without changing singleton semantics. |
| P1.1 | health, error format, archive/build boundary | Test must prove liveness and source isolation without reading archive. | Boundary scanner is restricted to backend source and archive is ignored by Git/Docker. |
| P1.2 | crypto purpose/AAD and audit metadata | Secret domains and metadata rejection are security-sensitive. | Implement purpose allowlist, AEAD AAD binding, and secret-key metadata rejection; no production key reads in tests. |
| P1.3 | CSRF, TOTP replay, recovery, session revocation | Authentication failure paths are load-bearing and must be tested through real API flows. | Keep password login as challenge-only and require server-side MFA before setting the admin session. |

## Rulings

- Ruling: all implementation remains in the new X-ray repository and uses mock/local infrastructure only - the specification forbids Shop migration and real cloud writes - external state is unchanged.
- Ruling: preserve the pre-existing empty `nodes/`, `xray_service/`, and `static/` skeletons - the project README and plan explicitly reserve business code for `backend/` and `frontend/` - future boundary tests must exclude these legacy placeholders from runtime discovery.

## Task status

- Task P1.1: in progress
- Task P1.2: pending
- Task P1.3: pending
