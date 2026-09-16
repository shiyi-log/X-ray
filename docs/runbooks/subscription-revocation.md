# 订阅强制撤销运行手册

## 适用范围

强制撤销同时使订阅 Token 失效，并尝试在每个相关节点上删除旧访问凭据。它不删除实例、不释放 IP，也不承诺清除用户设备已保存的历史订阅内容。真实云防火墙、远程 SSH、IPv4/IPv6 和公网数据面仍需单独授权验收。

## 状态含义

| 状态 | 可证明事实 | 不能声称的事实 |
| --- | --- | --- |
| `REVOKING` | Token 已 tombstone，发布已冻结，后台正在处理节点 | 节点旧连接已经全部失效 |
| `VERIFIED_REVOKED` | 固定 generation 已应用；旧凭据新握手被拒绝；旧持续会话关闭；正向控制成功 | 未测试传输、真实公网或客户端缓存已清除 |
| `QUARANTINED` | 防火墙回读和数据面证据证明节点整体被隔离 | 指定身份已从节点配置中精确删除 |
| `REVOCATION_UNCONFIRMED` | 精确撤销证据不完整，隔离也未充分确认 | 旧凭据失效 |
| `ISOLATION_UNCONFIRMED` | 云规则或数据面隔离证据不足 | 节点不可达 |

`PARTIALLY_SUCCEEDED` 必须保留红色风险提示和未完成节点；不得改写成“撤销成功”。已 tombstone 的 Token 始终返回 410，即使节点处理或 PublicationBatch 失败。

## 执行顺序

1. 用最近 step-up 创建绑定 profile、状态快照、影响节点和确认文本的短期 ActionPreview。
2. 提交带 UUID `Idempotency-Key` 的 `subscription.revoke`。同一事务消费预览、将 profile 置为 `REVOKING`、冻结发布、撤销 Token、使当前修订不可用、创建 Operation/outbox 与逐节点状态。
3. worker 捕获旧凭据持续会话证据；共享协议将全部旧共享引用纳入影响集，并为仍有效 profile 生成新代密钥。
4. 生成不含撤销身份的配置，使用严格递增 generation 调用 `NodeExecutor.apply_config(..., allow_security_rollback=False)`。
5. 对每个旧 credential_ref 发起全新握手，并关联持续连接关闭证据；同节点/协议/地址族/传输时间窗内的正向控制必须成功。
6. 精确验证失败时，先使受影响修订 unusable 并排除节点，再调用独立 `node.quarantine` 操作。隔离异常保持 `REVOCATION_UNCONFIRMED`。

OperationStep 只保存节点 ID、generation、布尔结果和计数，不保存原始凭据、订阅正文或 Token。

## 共享协议影响

固定 Xray 版本下，Shadowsocks endpoint 使用共享密码。撤销任一引用该 endpoint 的 profile 时，旧共享密码对所有 profile 一起失效；仍有效 profile 获得新密码和新 generation，必须刷新订阅或重新导入。危险预览和控制台必须显示完整影响身份清单，不能把共享密码描述成单设备撤销。

## 失败处置

- SSH 或配置应用失败：禁止恢复含撤销身份的旧配置；立即执行发布失效与隔离流程。
- 云 API 写入结果不明：保留资源和配额，进入对账；不得重复创建、自动删除或释放 IP。
- 防火墙 ACK 但没有回读/数据面证据：记录 `ISOLATION_UNCONFIRMED`，不能记录 `QUARANTINED`。
- positive control 失败或只有超时：记录 `REVOCATION_UNCONFIRMED`；超时不是认证拒绝证据。
- 重试只处理未到 `VERIFIED_REVOKED` 的节点；令牌失效检查点之后 `can_cancel=false`。

## 恢复与人工复开

恢复数据库后先进入 `MAINTENANCE`：有效订阅返回 503，普通云写和节点 start/reboot/reinstall 被拒绝。使用独立、追加保存的安全事件副本执行：

```bash
XRAY_ENV=production uv run --project backend python backend/manage.py \
  reconcile_security_state \
  --events /restricted/security-events.json \
  --expected-sequence <verified-sequence>
```

事件必须从 1 到 expected sequence 连续、digest 与既有记录一致，最后一条为已验证的 `RESTORE_VERIFIED`，且明确证明 `tokens_reconciled=true` 与 `credentials_rotated=true`。任一缺口、重放变更、文件错误或轮换证据不足都保持 `MAINTENANCE`。

隔离节点只允许人工复开：先在受限探测源验证所有历史撤销身份缺席、新凭据成功和 generation/hash 一致，再最小化开放规则并重复正反向探测。异常时重新隔离。客户端传入 `verified_restore=true` 没有授权效果。

## 本地证据与外部边界

本地固定运行时门禁：

```bash
XRAY_ENV=test \
XRAY_TEST_DATABASE_URL='postgresql://xray_test:xray_test_only_password@127.0.0.1:55432/xray_test' \
XRAY_REDIS_URL='redis://127.0.0.1:56379/0' \
XRAY_TEST_BINARY="$PWD/runtime/xray/v26.3.27/xray" \
XRAY_REQUIRE_FIXED_BINARY=1 \
backend/.venv/bin/pytest -c backend/pyproject.toml \
  tests/subscriptions/test_xray_revocation.py -q
```

该测试覆盖本机 TCP/无 TLS 的 Shadowsocks、SOCKS5、VMess、VLESS、Trojan，以及共享 Shadowsocks 旧配置的联动失效。UDP、TLS/证书、远程 SSH、真实 AWS/SWAS 防火墙、IPv4/IPv6 公网探测和 Shadowrocket 真机导入在获得具体授权前保持 `not-run` 或 `blocked`。
