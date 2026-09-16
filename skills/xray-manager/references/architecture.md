# Architecture Reference

The system is a modular Django monolith plus a separate Vben frontend. PostgreSQL is the source of truth; Redis/Celery carries work but is reconstructible. The public subscription process has only subscription read/decrypt permissions and never receives control, cloud, SSH, or TOTP master keys.

## Phase ownership

- P1: `identity`, `audit`, `common`, authentication and encryption.
- P2: `cloud_accounts` and `providers` with AWS Lightsail/SWAS DTO and capability contracts.
- P3: `operations`, `nodes`, reliable workers, installation and probes.
- P4: `subscriptions`, renderers, token tombstones, revocation and recovery barrier.
- P5: `frontend`, OpenAPI generation and browser workflows.
- P6: deployment, Nginx boundaries, backup/restore and acceptance matrix.

## Shared interfaces

Keep `SecretStore.encrypt/decrypt`, `OperationService.submit`, `NodeExecutor.apply_config/probe`, and `NodeLifecycle.create/quarantine` signatures compatible with the checked-in implementation plan. API views enqueue work and return an operation identifier; they do not wait on cloud or SSH calls.
