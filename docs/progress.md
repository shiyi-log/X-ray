# 开发进度

本文件只记录已执行的命令和证据。状态只能使用 `passed`、`failed`、`blocked`、`not-run` 或 `risky_not_executed`；未授权的真实云/生产动作不得写成 `passed`。

| date | phase | task | commit | command | exit_code | evidence | status | rollback_ref |
| --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| 2026-09-17 | baseline | capture initial repository | `2da51e7` | `git show --stat --oneline HEAD` | 0 | `v0.0.0-baseline` | passed | `v0.0.0-baseline` |
| 2026-09-17 | P0 | migration/boundary/traceability | `2885503` | `./scripts/check-runtime.sh`; skill validator; `pytest backend/tests -q` | 0 | local command output | passed | `v0.0.0-baseline` |
| 2026-09-17 | P1 | administrator, MFA, encryption | `fb0a2db` | `pytest backend/tests -q`; `manage.py makemigrations --check --dry-run` | 0 | 13 passed | passed | `v0.0.1` |
| 2026-09-17 | P2 | dual-cloud contracts | `851f8dd` | `pytest backend/tests -q`; migration check; Ruff; boundary/secret scans | 0 | 30 passed; `docs/architecture/cloud-capabilities.md` | passed | `v0.1.0` |
| 2026-09-17 | P3 | operations, nodes, fixed installer and five-protocol runtime | `f4975a7` | `pytest backend/tests tests/installer -q`; Ruff; ShellCheck 0.10.0; migration/boundary/secret/diff gates | 0 | `artifacts/acceptance/0.3.0/backend-and-installer.junit.xml`; 66 passed | passed | `v0.2.0` |
| 2026-09-17 | P4 | subscriptions, fixed format parsers and fail-closed revocation | `aaf9913d4ed2eca5466c1b57f3c41f0228f029bd` | `pytest ... backend/tests tests/installer tests/subscriptions/test_xray_revocation.py`; `tests/subscriptions/verify_formats.sh`; migration/Ruff/ShellCheck/boundary/Gitleaks/skill gates | 0 | `artifacts/acceptance/0.4.0/backend-installer-revocation.junit.xml`; 111 passed; fixed Xray/Clash/Mihomo parser output | passed | `v0.3.0-nodes` |
| 2026-09-17 | P5 | independent Vben console and safe revocation controls | `fd23a51` / `ee02808` / `de1ab0b` | backend full pytest; frontend unit/typecheck/lint/build/E2E; OpenAPI double generation; migration/boundary/Gitleaks | 0 | `artifacts/acceptance/0.5.0/`; 120 backend tests; 11 frontend unit; 6 Chrome E2E | passed | `v0.4.0-subscriptions` |
| 2026-09-17 | P5 | Ruff availability gate | `de1ab0b` | `backend/.venv/bin/ruff check backend tests` | 127 | virtualenv tool absent; no pass claimed | failed | `v0.4.0-subscriptions` |
| 2026-09-17 | P5 | pinned Ruff fallback | `de1ab0b` | `uvx --from ruff==0.13.1 ruff check backend tests` | 0 | `All checks passed!` | passed | `v0.4.0-subscriptions` |
| 2026-09-17 | P6 | isolated production/staging delivery surfaces | `69a6301` | `pytest -c backend/pyproject.toml backend/tests tests/deploy -q`; Compose/preflight tests | 0 | dedicated Compose, dual Nginx surfaces, non-root runtime images and application-only rollback | passed | `v0.5.0-console` |
| 2026-09-17 | P6 | encrypted backup and revocation-safe recovery | `ad30634` | `pytest -c backend/pyproject.toml tests/recovery backend/tests/subscriptions -q` | 0 | encrypted backup/restore, permanent tombstone, external security ledger and `MAINTENANCE` barrier | passed | `v0.5.0-console` |
| 2026-09-17 | P6 | CI and acceptance evidence contracts | `e047495` | `pytest -c backend/pyproject.toml tests/acceptance tests/deploy -q` | 0 | 35 focused acceptance/deployment tests; matrix and real-cloud/production evidence validator | passed | `v0.5.0-console` |
| 2026-09-17 | P6 | first unified gate exposed skipped image tests | `e047495` + dirty tree | `./scripts/check-local.sh` | 0 | 178 passed / 3 skipped; image environment variables were lost in a pipeline subshell, so this run is invalid and not acceptance evidence | failed | `v0.5.0-console` |
| 2026-09-17 | P6 | one-time Token trace hygiene regression | `c229c7fcf2574d3a024420da686b4abe4ef6ddc0` | `pnpm --dir frontend exec playwright test --config playwright.config.ts tests/e2e/full-flow.spec.ts --project=desktop-chromium` | 0 | 2 passed; trace starts after Token DOM removal, network archive removed, ZIP bytes checked without logging the Token | passed | `v0.5.0-console` |
| 2026-09-17 | P6 | commit-bound unified local delivery gates | `c229c7fcf2574d3a024420da686b4abe4ef6ddc0` | `./scripts/check-local.sh` | 0 | `artifacts/acceptance/0.6.0/gates/summary.tsv`; 181 passed / 0 skipped; 11 frontend unit; 7 Chrome E2E | passed | `v0.5.0-console` |
| 2026-09-17 | P6 | real encrypted restore measurement | `c229c7fcf2574d3a024420da686b4abe4ef6ddc0` | `xmllint --xpath ... artifacts/acceptance/0.6.0/gates/backend-and-delivery.junit.xml` | 0 | `artifacts/acceptance/0.6.0/recovery-measurement.json`; 2.043s local test duration | passed | `v0.5.0-console` |
| 2026-09-17 | P6 | project skill validation | `c229c7fcf2574d3a024420da686b4abe4ef6ddc0` | `python3 /Users/a399/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/xray-manager` | 0 | `Skill is valid!`; `artifacts/acceptance/0.6.0/gates/skill.log` | passed | `v0.5.0-console` |
| 2026-09-17 | external | AWS/SWAS and production release | - | not executed: authorization/server/domain/budget unavailable | - | `tests/acceptance/matrix.json` | blocked | `v0.5.0-console` |
| 2026-09-17 | external | Shadowrocket device, remote SSH and Google public probe | - | not executed: external test target unavailable | - | `tests/acceptance/matrix.json` | not-run | `v0.5.0-console` |
| 2026-09-17 | external | instance deletion and static IP release | - | not executed: destructive authorization unavailable | - | `tests/acceptance/matrix.json` | risky_not_executed | `v0.5.0-console` |

真实 AWS/SWAS、远程 SSH、Google 公网探测、独立生产服务器、实例删除和 IP 释放在获得具体授权前保持 `blocked` 或 `not-run`。

P3 的真实 Xray 证据使用哈希固定的 macOS arm64 `v26.3.27` 本地二进制，完成 Shadowsocks、SOCKS5、VMess、VLESS、Trojan 到本机 HTTP 目标的实际链路测试。该证据不代表 Linux 远程 SSH、真实云或公网可用性。

P4 在固定 Xray `v26.3.27` 上验证五类协议的旧持续连接关闭、旧凭据新握手拒绝和新凭据正向连接，并用 Clash `v1.18.0`、Mihomo `v1.19.12` 与独立 Shadowrocket URI 解析器验证四种格式。Shadowrocket 真机、UDP、TLS 证书链、真实云、远程 SSH、公网 Google 探测和生产服务器仍没有执行证据。

P5 使用本机 Google Chrome、真实 Django/PostgreSQL/Redis 和测试 Fake 资源验证密码/TOTP、刷新恢复、空状态、断网错误、固定 Operation、一次性交付、危险确认、部分撤销及 `390x844` 移动布局。测试种子命令仅允许专用 `xray_test` 数据库；没有执行真实云写入、SSH、公网探测或生产发布。

P6 的有效统一门禁在提交 `c229c7fcf2574d3a024420da686b4abe4ef6ddc0` 上执行。恢复测试使用专用 PostgreSQL，真实调用 `pg_dump`、age 加/解密与 `pg_restore`，恢复到临时 `xray_restore_<uuid>` 数据库，补入备份后撤销事件并验证旧 Token 仍为 gone，最后删除临时数据库。该测量不是生产 RTO，也没有使用生产 dump、密钥或服务器。
