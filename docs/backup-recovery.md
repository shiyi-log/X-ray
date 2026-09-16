# 加密备份与隔离恢复

## 安全模型

数据库备份只包含业务时点状态，不能证明备份之后是否发生撤销。因此恢复同时依赖两条独立证据链：age 加密的 PostgreSQL custom dump，以及持续外送、带前一摘要的安全事件账本。恢复脚本永远创建新的 `xray_restore_*` 数据库，并在任何应用连接前直接写入 `MAINTENANCE`、节点维护状态和新 worker fence。它不会覆盖运行库，也不会自动开放订阅或云写。

Token 撤销会同时产生永久 `RevocationTombstone`、哈希链 `SecurityEventRecord` 和待外送 `SecurityEventOutbox`。独立账本写入失败时 `security_backup_lagging=true`，此状态下不能导出可用于恢复的“最新”快照。账本能发现缺口和冲突，但不声称抵抗已经控制数据库与离机存储两端的攻击者。

## 固定工具

构建工具镜像时固定 PostgreSQL 17.6 基础摘要、age 1.2.1 和 jq 1.8.1；age/jq 的 amd64、arm64 资产都在 Dockerfile 中校验 SHA-256：

```bash
docker build -f deploy/docker/backup-tools.Dockerfile \
  -t registry.example/xray/backup-tools:0.6.0 .
```

推送后把 registry 返回的不可变 digest 写入服务器配置的 `XRAY_BACKUP_TOOLS_IMAGE`。发布脚本通过 `deploy/backup/run-in-tools.sh` 运行该镜像，不使用宿主机的随机版本工具。

## 每日与发布前备份

1. security-ledger dispatcher 必须无待发送记录。
2. 使用 `export_security_events --output <absolute-new-file>` 生成已校验快照；命令拒绝覆盖现有文件和账本落后状态。
3. `pg_service.conf` 使用只读备份角色，`pgpass` 权限为 `0400/0600`，密码不进入 argv。
4. 执行固定工具包装器：

```bash
deploy/backup/run-in-tools.sh --config /etc/xray/config.env backup \
  --destination /var/lib/xray/offsite-staging
```

输出目录只包含 `database.dump.age` 与 `manifest.json`。明文 dump 只存在于权限 0700 的 `mktemp` 目录，并在成功、失败或信号退出时清理。manifest 记录版本、镜像、安装器、密钥版本、明/密文摘要和独立安全账本序号/摘要，不包含口令、主密钥或 raw token。

备份完成后必须把整个目录复制到独立账号/区域的不可变存储，并记录存储端对象版本或保留锁确认。本地目录存在不等于离机成功。

## 校验与恢复演练

恢复私钥只在审批后的隔离环境临时挂载：

```bash
deploy/backup/verify.sh \
  --backup /restore/input/xray-0.6.0-... \
  --identity /run/recovery/age-identity.txt

deploy/backup/restore.sh \
  --backup /restore/input/xray-0.6.0-... \
  --target xray_restore_20260917_drill \
  --config /run/recovery/config.env \
  --identity /run/recovery/age-identity.txt
```

`verify.sh` 校验密文摘要、解密后摘要和 `pg_restore --list`。`restore.sh` 拒绝现有数据库及非 `xray_restore_*` 名称，使用 `--no-owner --no-acl` 导入，然后写入恢复锁。恢复 receipt 记录实际时长、manifest 摘要、隔离网络和维护状态，可放入脱敏验收目录。

随后在恢复数据库上执行：

```bash
XRAY_RECOVERY_CONFIRM=MAINTENANCE \
python backend/manage.py reconcile_after_restore \
  --settings=config.settings.recovery \
  --confirm 'LOCK RESTORED SYSTEM' \
  --events /restore/evidence/security-current.json \
  --expected-sequence <offsite-confirmed-sequence>
```

此命令导入较新撤销事件并生成 tombstone，但即使事件副本带有最终证明也保持维护状态。所有旧身份失效使用 `rotate_after_restore` 的精确确认和审批引用；真实云/节点写仍需另行授权和证据。全部外部操作完成后，用 `record_restore_verification` 读取脱敏 proof 文件并记录新的 `RESTORE_VERIFIED` 事件。proof 必须同时证明 `tokens_reconciled`、`credentials_rotated`、`audit_caught_up`、`old_credentials_rejected` 并列出证据引用；该命令仍不会自动开放。事件外送并形成独立完整快照后，人工复核才调用正式 reconciliation 开放。

## RPO、RTO 与保留

- 目标 RPO：24 小时；每日和每次发布前备份，独立安全账本持续外送。
- 目标 RTO：4 小时；每月在隔离数据库和无公网 worker 网络中实测。
- 保留：至少 7 个每日点和 4 个每周点。`retention.sh` 默认只预览，`--apply` 也只移动到同一存储的 `.trash`，不会不可逆删除。
- 恢复演练必须记录实际开始/结束、数据库大小、manifest 摘要、目标库、账本序号、旧 token 410、有效旧 token 503、worker 云写拒绝和清理结果。
