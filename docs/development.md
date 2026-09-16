# 本地开发

## 隔离依赖

P1 使用独立 PostgreSQL 17 和 Redis 7.4，Compose 项目名固定为 `xray-test`。宿主机端口只绑定 loopback：

| 服务 | 容器端口 | 宿主机端口 | 数据库/实例 |
| --- | ---: | ---: | --- |
| PostgreSQL | 5432 | 55432 | `xray_test` |
| Redis | 6379 | 56379 | DB `0` |

端口已在本机检查无监听，不应停止其他项目来抢占端口。若端口发生冲突，先重新执行端口检查并更新本项目配置与注册记录。

```bash
cp backend/.env.example backend/.env
make compose-up
make compose-config
```

测试数据库不会使用 SQLite，也不会连接 Shop 的数据库。测试结束后可执行 `make compose-down`；命名卷仅保存本项目测试数据，需要完全重建时再显式删除 `xray-test-postgres` 和 `xray-test-redis`。

## 本地门禁

```bash
make check-boundary
make secret-scan
uv run --project backend python backend/manage.py check --settings=config.settings.test
uv run --project backend pytest -c backend/pyproject.toml backend/tests -q
```

真实 AWS、阿里云、SSH、Google 探测、服务器部署和生产密钥不属于本地测试流程；测试中的云和 SSH 必须使用 stub/fake。
