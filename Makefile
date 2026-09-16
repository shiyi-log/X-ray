.PHONY: compose-up compose-down compose-logs compose-config test check-boundary secret-scan check-runtime check

COMPOSE := docker compose -p xray-test -f deploy/compose/test.yml

compose-up:
	$(COMPOSE) up -d --wait

compose-down:
	$(COMPOSE) down

compose-logs:
	$(COMPOSE) logs --tail=100

compose-config:
	$(COMPOSE) config --quiet

test: compose-up
	uv run --project backend pytest -c backend/pyproject.toml backend/tests -q

check-boundary:
	./scripts/check-boundary.sh

secret-scan:
	./scripts/check-secrets.sh

check-runtime:
	./scripts/check-runtime.sh

check: compose-config check-boundary secret-scan
