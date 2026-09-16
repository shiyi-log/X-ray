# P6 独立部署、恢复与验收 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可独立部署、可恢复且验收边界清楚的完整新产品。

**Architecture:** Debian 12 独立控制服务器以 Compose 运行内部服务，Nginx 隔离管理和订阅入口。加密离机备份配合恢复锁定与凭据追平；CI 完成本地门禁，真机按明确授权另行验收。

**Tech Stack:** Docker Compose、Nginx、PostgreSQL 17、Redis 7.4、Gunicorn、Celery、pg_dump/pg_restore、age、Playwright、ShellCheck、Gitleaks。

**Spec:** [设计规格](../specs/2026-09-16-xray-manager-design.md)，章节 3、5、11–12。

## Global Constraints

- 控制服务器、数据库、Redis、密钥和备份全部独立；不能从 Shop 的 .env 或归档补配置。
- archive/ 禁止构建/备份/CI artifact 进入；镜像版本固定摘要，管理面私有。
- 代码验收、真实双云验收、生产发布分开报告；本阶段计划不授权实际创建/删除资源。
- 删除实例和释放 IP 独立确认；本地测试通过不能替代真实网络证据。

---

### Task P6.1: 最小部署权限、双入口与发布回滚

**Files:**
- Create: `deploy/compose/{production,staging}.yml`、`deploy/docker/{backend,frontend}.Dockerfile`、`deploy/nginx/{admin,subscription,default-deny}.conf`。
- Create: `deploy/postgres/roles.sql`、`deploy/scripts/{preflight,release,rollback}.sh`、`deploy/secrets.example.md`。
- Test: `tests/deploy/{test_network_boundary,test_image_contents,test_release_compatibility}.py`。
- Modify: `.dockerignore`、`backend/config/{settings/production,subscription_urls}.py`、`docs/{deployment,release}.md`。

**Interfaces:**
- `preflight.sh --config <non-secret-config>` 只检查，exit非零缺配置；`release.sh --version <version> --digest <digest>` 按规格执行检查点；`rollback.sh --version <previous>` 只恢复应用。
- admin-api：DB 业务读写、control/subscription secrets；subscription-api：只读订阅表、subscription secret，无 control key；worker：有限云/SSH权限；outbox-dispatcher：仅队列投递。
- 管理 allowlist/域名只能由服务器部署配置变更，Web显示只读。实例归属校验排除控制服务器身份。

- [ ] **Step 1: 编写网络/镜像失败检查。**

```python
def test_public_host_cannot_reach_admin(public_client):
    assert public_client.get('/api/v1/cloud-accounts').status_code == 404
    assert public_client.get('/admin/').status_code == 404

def test_subscription_process_has_no_cloud_secret(subscription_container):
    result = subscription_container.exec_run('test -e /run/secrets/control-master-key')
    assert result.exit_code != 0

def test_image_has_no_archive(image_members):
    assert not any('/archive/' in name or '/.shop-secrets/' in name for name in image_members)
```

fixtures 用测试 Compose 容器/镜像 tar list，不从宿主机真实服务器获取。补：伪造 Host/Forwarded、IPv6未限制、直接容器端口、订阅URL日志、DB角色写审计/读云凭据失败测试。
- [ ] **Step 2: 运行 `uv run --project backend pytest -c backend/pyproject.toml tests/deploy -q` 确认缺少部署契约失败。**
- [ ] **Step 3: 实现入口和构建 allowlist。**

```dockerfile
# backend Dockerfile 关键边界
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./backend/
# 安装锁定依赖后只复制应用需要的目录
COPY backend/ ./backend/
COPY installer/ ./installer/
```

```nginx
# public host: 不记录 token 路径，不反代其他接口
location ~ ^/s/[A-Za-z0-9_-]{43}$ {
    limit_except GET HEAD { deny all; }
    access_log off;
    proxy_pass http://subscription-api:8000;
    proxy_no_cache 1;
    proxy_cache_bypass 1;
}
location / { return 404; }
```

Token 编码固定为32字节无padding的base64url=43字符，后端同样验证。管理虚拟主机 allowlist、CSRF trusted origin 精确配置；默认 Host 拒绝；后端代理来源可信列表固定。DB role 权限让订阅进程无法读control ciphertext，让普通应用无法UPDATE/DELETE审计表。

发布脚本先 backup 和 migrate --plan，再 migrate，随后 migrate --check；worker drain 至检查点后切换，过长操作进入显式维护状态，不 kill 后假定回滚。回滚只换镜像不恢复旧凭据/云资源。
- [ ] **Step 4: 校验 Compose、镜像内容、上版兼容迁移和回滚。**

```bash
docker compose -p xray-stage -f deploy/compose/staging.yml config --quiet
bash -n deploy/scripts/preflight.sh deploy/scripts/release.sh deploy/scripts/rollback.sh
shellcheck deploy/scripts/preflight.sh deploy/scripts/release.sh deploy/scripts/rollback.sh
uv run --project backend pytest -c backend/pyproject.toml tests/deploy -q
```

- [ ] **Step 5: 提交 `feat: isolate deployment surfaces and safe release workflow`。** 开发 secrets 只在临时目录，未进入索引。

### Task P6.2: 加密离机备份、密钥托管与恢复锁定

**Files:**
- Create: `deploy/backup/{backup,restore,verify,retention}.sh`、`deploy/backup/manifest.schema.json`、`docs/{backup-recovery,key-rotation,incident-response}.md`。
- Create: `backend/apps/operations/management/commands/reconcile_after_restore.py`、`backend/apps/subscriptions/management/commands/rotate_after_restore.py`。
- Modify: `backend/apps/subscriptions/security.py`（P4 SecurityBarrier）、`backend/apps/audit/services.py`。
- Test: `tests/recovery/{test_restore_lockdown,test_backup_manifest,test_revocation_never_reactivates}.py`。

**Interfaces:**
- `backup.sh --destination <configured-store>` 产生加密 dump+manifest；manifest包括 schema/app/image/installer/key versions、checksums、时间，不含秘密。
- `restore.sh --backup <file> --target <fresh-db>` 强制创建隔离恢复目标并设置 SecurityBarrier，无法对运行库静默覆盖。
- `reconcile_after_restore` 只读取证；`rotate_after_restore` 只有再次明确授权后才创建云/节点写操作。
- `SecurityBarrier.assert_open(purpose='public_read'|'cloud_write'|'reopen_node')` 由 P4 定义。恢复审计追平/全量轮换前全部拒绝。

- [ ] **Step 1: 写旧备份不得复活撤销身份测试。**

```python
def test_old_backup_never_serves_old_credentials(restored_system):
    assert restored_system.security_mode == 'MAINTENANCE'
    assert restored_system.get('/s/' + restored_system.old_token).status_code == 503
    assert restored_system.worker.claim_cloud_write() is None
    restored_system.import_revocation_ledger()
    assert restored_system.can_open_public is False
    restored_system.verify_reconciliation_and_key_rotation()
    assert restored_system.get('/s/' + restored_system.old_token).status_code == 410
```

restored_system fixture 使用本地容器中的真实 pg_restore、Fake providers 与 P4流程；不是只改一个内存布尔值。补：丢失主密钥、丢备份私钥、密文key_version不支持、离机安全日志缺口、云状态不明、outbox重复恢复。
- [ ] **Step 2: 运行 `uv run --project backend pytest -c backend/pyproject.toml tests/recovery -q` 预期失败。**
- [ ] **Step 3: 实现 dump→加密→校验→离机确认流程和独立密钥托管。**

```bash
# 文件路径由脚本在 mktemp -d 创建的0700目录中解析；secret不放argv
pg_dump --format=custom --file="$backup_temp/database.dump" "$XRAY_BACKUP_DB_ALIAS"
age -r "$backup_recipient" -o "$backup_temp/database.dump.age" "$backup_temp/database.dump"
```

DB别名引用只读 PG service 文件，密码在0600文件；age recipient为公开加密recipient。明文dump权限0600且完成后清理；恢复私钥和control/subscription主密钥分别离机托管，登记版本和双份可恢复验证，不把明文钥匙塞入DB备份。

审计 outbox 将安全事件序号、前一摘要和事件摘要发送到配置的离机追加存储；完整性链用于发现缺口，不宣称能防root篡改。外送失败标记安全备份落后并告警，不能据此证明撤销状态新鲜。恢复无法确认完整安全日志时保持关闭，并完成所有旧Token及节点凭据失效处理才能开放。

- [ ] **Step 4: 从实际加密备份在新DB恢复，测量RPO/RTO。** 验证管理员、密文解密、节点资源、撤销tombstone、审计序列、redis重建、租约旧worker拒绝、no-network默认；记录实际耗时和是否达到24h/4h目标。
- [ ] **Step 5: 提交 `feat: add encrypted backup and revocation-safe recovery`。** 文档给出每日/发布前备份、7日4周保留、每月隔离演练命令。

### Task P6.3: 全门禁、双云授权验收与交付台账

**Files:**
- Create: `.github/workflows/ci.yml`、`scripts/check-local.sh`、`tests/acceptance/matrix.json`、`docs/{acceptance,cloud-test-authorization,release-checklist}.md`。
- Create: `tests/e2e/full-flow.spec.ts`、`tests/acceptance/test_matrix.py`。
- Modify: `README.md`、`docs/progress.md`。

**Interfaces:**
- `scripts/check-local.sh` 按后台/安装器/OpenAPI/前端/部署/E2E顺序执行，任一失败非零退出；真实云动作没有CI入口。
- matrix 每项 `id,environment,status,evidence,commit,provider,region,cost,residual_resources`，status仅 `passed/failed/blocked/not-run/risky_not_executed`。
- 真机授权表包括具体账号、区域、套餐/镜像、预算、最长存活时间、允许动作、停机/删除/IP释放各自确认；预算超限停止新增资源但不能自动销毁。

- [ ] **Step 1: 写验收台账不得虚报和真实浏览器全流程测试。**

```python
def test_real_cloud_pass_requires_real_evidence():
    row = {'environment': 'real_cloud', 'status': 'passed', 'evidence': ['mock-report.json']}
    with pytest.raises(ValueError, match='真实云证据'):
        validate_row(row)
```

`validate_row` 在 `tests/acceptance/test_matrix.py` 同任务定义并由matrix校验CLI复用：真实云证据必须包含授权引用、完整操作ID、外部请求ID、脱敏资源、时间和探测结果，不以文件名判断真实。
- [ ] **Step 2: 运行失败测试与端到端流程，确认遗漏页面/契约可见。**
- [ ] **Step 3: 实现CI和本地统一门禁。**

```bash
uv run --project backend python backend/manage.py check --settings=config.settings.test
uv run --project backend python backend/manage.py makemigrations --check --dry-run --settings=config.settings.test
uv run --project backend pytest -c backend/pyproject.toml backend/tests tests/installer tests/deploy tests/recovery tests/acceptance -q
pnpm --dir frontend typecheck
pnpm --dir frontend lint
pnpm --dir frontend test:unit
pnpm --dir frontend build
pnpm --dir frontend test:e2e
```

增加OpenAPI可重现检查、Gitleaks仅扫描tracked diff/发布allowlist、docker context成员清单、禁Shop import、shell检查。CI数据库和Redis只用工作流容器假凭据，云SDK默认Stub；本地协议测试不请求Google，真实Google仅授权验收。
- [ ] **Step 4: 完成代码门禁报告。** 每门禁填写命令、commit、退出码、报告链接；未获授权的云/生产项保留 `blocked` 或 `risky_not_executed`，代码可独立判定完成。
- [ ] **Step 5: 获得具体授权后执行两平台真实矩阵，保留费用与残留清单。** 创建→安装→五协议检测→四订阅解析→旧持续连接与新连接→强制撤销→SSH故障/防火墙失败→隔离→恢复→重放/幂等；按能力测试换IP或替代节点；删除与IP释放只执行已明确获准项。
- [ ] **Step 6: 真实独立服务器验证私有管理/TLS/备份/恢复后，更新发布判定；提交 `ci: enforce xray delivery acceptance gates`。** 若真机授权未到，不伪造Step5/6结果；保留清晰待执行项。

## P6 完成门禁

- [ ] 代码交付：所有本地门禁 passed、文档可重现、秘密/归档没有进入产物。
- [ ] 恢复演练：旧备份启动关闭、恢复钥匙可用、撤销不复活、目标RPO/RTO有实测。
- [ ] 运行验收：AWS与SWAS分别有真实证据；剩余收费实例/IP列清单；未授权项明确标记。
- [ ] 发布：独立域名/服务器/凭据完成配置后才判定上线，Git提交和CI通过不是上线证明。
