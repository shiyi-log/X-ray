#!/usr/bin/env bash
# Run in a clean source export. Tests open temporary listeners: on this Mac use
# an isolated container without published ports, not the existing host services.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
python3 scripts/check-baseline.py
export HUSKY=0
npm --prefix frontend ci --no-audit --no-fund
npm --prefix frontend run lint
npm --prefix frontend run format:check
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run build
go mod download
go mod verify
export ZONEINFO="$(go env GOROOT)/lib/time/zoneinfo.zip"
go test -shuffle=on -count=1 ./...
go vet ./...
mkdir -p build
go build -trimpath -o build/x-ui .
python3 scripts/check-baseline.py
