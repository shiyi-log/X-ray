# 2026-09-18 本地运行核验

仅限本机开发环境；没有执行真实云、SSH、公网探测或生产操作。

| command | exit_code | result |
| --- | ---: | --- |
| `make compose-up` | 0 | `xray-test-postgres-1`、`xray-test-redis-1` healthy |
| `uv run --project backend python backend/manage.py migrate --noinput` (loaded `backend/.env` locally) | 0 | No migrations to apply |
| `uv run --project backend python backend/manage.py runserver 127.0.0.1:8000` (loaded `backend/.env` locally) | running | `127.0.0.1:8000` listening |
| `pnpm --dir frontend dev` | running | Vite ready at `http://127.0.0.1:5178/` |
| `curl -sS -i --max-time 5 http://127.0.0.1:8000/health/live` | 0 | HTTP 200, `status=ok` |
| `curl -sS -i --max-time 5 http://127.0.0.1:8000/health/ready` | 0 | HTTP 200, database and Redis `ok` |
| `curl -sS -i --max-time 5 http://127.0.0.1:5178/` | 0 | HTTP 200, X-ray frontend HTML |
| `curl -sS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:5178/api/v1/auth/session` | 0 | HTTP 200 via Vite proxy; response body not recorded |
| `docker compose -p xray-test -f deploy/compose/test.yml ps` | 0 | Dedicated PostgreSQL and Redis healthy on loopback ports `55432` and `56379` |
| `manage.py shell -c '... SuperAdmin.objects.count()'` (loaded `backend/.env` locally) | 0 | One administrator record exists; account and credential values were not read |
| `./scripts/check-boundary.sh` | 0 | `boundary check passed` |
| `git diff --check` | 0 | No whitespace errors in tracked changes |

Unprivileged local `curl` checks failed with connection errors due to the command sandbox; the same checks succeeded in the authorized local context. The first frontend start failed with `listen EPERM` inside the sandbox and succeeded after authorization. The administrator count query initially failed because the sandbox denied access to the `uv` cache, then succeeded after authorization. No ports or processes belonging to another project were stopped.
