# 订阅管理与验证

本轮变更包含身份与套餐策略、独立协议分配、一次性链接交付、发布历史、累计流量采集和到期/超额下发。界面入口为「订阅」→「创建订阅」或「管理」。先登记节点协议，再为身份选择协议；配置尚未成功应用时不能把订阅当作可用版本发布。

## 运行准备

先应用 `subscriptions.0005_subscriptionmutation_subscriptionplan_and_more`。迁移只增加表与字段，不清空既有身份、节点或会话。套餐保存到身份时快照有效期与配额；变更套餐不会清空累计用量。时间输入必须带时区，服务端以 UTC 比较，在 `now >= expires_at` 时到期。

节点配置下发需显式设置 `XRAY_NODE_TRANSPORT_FACTORY=apps.subscriptions.node_agent.aws_transport`；可信流量采集需 `XRAY_USAGE_FETCHER=apps.subscriptions.node_agent.fetch_usage`。这些配置会触发真实 SSH，只能在已授权的节点范围启用。AWS 适配器要求已批准的主机指纹；临时访问凭据仅驻留内存。`XRAY_ALLOW_REGIONAL_DEFAULT_KEY` 默认关闭，仅在明确授权的环境才允许开启。

需要运行既有操作 outbox/worker 和 Celery beat。`refresh_usage_and_limits` 每 60 秒调度一次，亦可通过 `refresh_subscription_usage` 管理命令执行。启用 worker 前应检查待执行操作及目标归属；不能为了测试直接消费未知的既有云操作。当前本地启动器不自动启用这些真实节点任务。

公网交付可用 `XRAY_PUBLIC_SUBSCRIPTION_BASE_URL` 配置可信 HTTPS 地址。链接只交付一次，签发/轮换/发布/编辑必须携带 UUID `Idempotency-Key`；重复交付请求不会恢复原始令牌。交付弹窗仅在内存保留秘密，到时或关闭即清除。撤销令牌永久返回 410。

## 节点与计量限制

Trojan 必须有 TLS 配置。证书与私钥须预置于 `/usr/local/etc/xray/certs/` 下，协议登记保存不带扩展名的路径；安装器将 `.crt`/`.key` PEM 内联到受保护配置，使 systemd DynamicUser 不需要直接读取根用户私钥。密钥、配置及 URI 不可进入日志或报告。

采集器读取节点回环 StatsService，不开放公网统计写接口。累计计数按节点、身份、进程/启动/代数、序列去重，不重置节点计数。尚未采集显示「尚未采集」，不表示用量为零。SOCKS5 无可靠的每账户流量统计，界面标识部分覆盖；有限配额身份不能分配 SOCKS5。

公网订阅读取立即拒绝到期/超额身份；已导入客户端的节点访问需要后台任务成功应用配置后才移除。采集周期、队列延迟及失败均会影响执行时间，当前配额不是无超量的实时计费承诺。

强制撤销保留既有失效关闭流程：先停用链接，再要求配置应用、旧凭据拒绝及正向控制证据。当前默认生产撤销执行器仍未配置，不能把链接 410 或本地 Stub 测试当作生产旧连接已终止；未确认状态必须显示风险，按既有隔离流程处理。

## 部署前检查

可执行 `python backend/manage.py check_subscription_runtime` 做只读检查；它不会 SSH、连接节点或派发队列。`--strict` 在传输、采集、撤销和 worker/scheduler 尚未形成可验证闭环时返回失败。

## 可复现测试

- 后端测试用专用 PostgreSQL/Redis；全量认证测试必须 `XRAY_DISABLE_TOTP=0`，不得沿用本地登录旁路。
- `pnpm --dir frontend test:unit`、`lint`、`build` 验证界面和类型。
- `pnpm --dir frontend exec playwright test --config playwright.subscriptions.config.ts` 使用隔离浏览器和拦截的 `/api/v1/**` 测试接口，不重置当前数据库，不保存截图、视频或 trace。
- `tests/installer/test_fixed_xray_runtime.py` 使用锁定 Xray 26.3.27 验证五协议 TCP/UDP。默认只访问回环测试服务。
- 仅在获得公网探测授权后设置 `XRAY_RUN_PUBLIC_PROBES=1`，通过本地 SOCKS 入口及五种代理协议请求 Google generate_204 和 YouTube 首页。需 `XRAY_TEST_BINARY` 指向锁定二进制。HTTPS 验证必须成功；20 秒超时、响应体上限 2 MiB，不下载视频。`XRAY_PUBLIC_PROBE_REPORT` 只保存非秘密状态证据。

2026-10-18 授权 AWS 临时节点实测：五协议到 Google 204、YouTube 200，10/10 成功。云实例在 19:11:38+08:00 已删除并完成单实例及列表缺失读回，控制器 89 秒。协议客户端与节点入口位于同一 Linux 主机回环地址；Trojan 此流量夹具未验证协议层 TLS，目标站点 HTTPS 证书已验证。此证据不覆盖公网入站、防火墙、真实终端、全部 WS/gRPC/TLS 组合或生产数据面撤销。费用上限为人民币 100 元，实际账单本轮未查询。

全部操作标识、门禁结果与回退边界见 `project-ledger.md` 与 `progress.md`。本轮不发布新版本或标签。回退仅撤销本轮源代码变更，保留新增表与安全审计；不得恢复已撤销令牌或云操作状态。
