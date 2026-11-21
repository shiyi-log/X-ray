# Active Architecture

The active application baseline is upstream MHSanaei/3x-ui `v3.11.0`, commit `c621ba9014a6aa21fd7c9ecf45655e44e24ebf13`. Exact imported file hashes live in the replacement manifest referenced by `UPSTREAM.json`. The archive source hash is also pinned there.

## Current modules

- `main.go`: panel process entry point. It is not run by a compile or unit-test gate.
- `internal/config/`: environment, paths, version metadata and application configuration.
- `internal/database/`: GORM and SQLite/PostgreSQL persistence.
- `internal/web/`: Gin routes, controllers, services and embedded web assets.
- `internal/xray/`: controller/runtime for a separately running Xray process. Compiling the panel does not start or verify Xray.
- `internal/sub/`: subscription endpoints and formats. This is upstream behavior; it does not imply old X-ray Manager token-digest revocation contracts.
- `frontend/`: React 19, TypeScript, Ant Design 6 and Vite output embedded at `internal/web/dist/`.
- `tools/`: upstream generators and support programs.

## Build relationship

`frontend/npm run build` generates the actual admin/login/subscriber assets and OpenAPI artifacts. The Go embed directive requires `internal/web/dist/` to exist. A blank stub is permitted only for backend-only unit tests; the deliverable binary must be built after the real frontend bundle. `go.mod`, `go.sum`, `.nvmrc`, and `frontend/package-lock.json` pin toolchain/dependencies. SQLite uses CGO.

The default upstream installer and runtime provisioning are not approved launch paths for this repository. The upstream example configuration enables debug mode and writes relative application state; inspect/replace it before any local panel start. First-run admin credential output also needs a reviewed delivery path.

## Not implemented by adopting the base

The prior Django application included custom step-up, idempotency, Lightsail inventory, durable operation audit, security-event persistence, subscription-pool publishing/revocation, restore maintenance barriers, and image-based online upgrades. None of those contracts may be inferred from this source tree. Each requested capability requires a new design, focused tests, threat review, and acceptance evidence.
