# v0.14.3 发布清单

## 本地验收

- [x] 在干净源码候选 `f2eac62d4d731c1f1ae4aba95191eb322bf8ecbd` 上运行 `scripts/check-local.sh`；19/19 门禁退出码为 0。
- [x] 后端与交付测试共 467 项：465 passed、2 skipped、0 failures/errors。两个 skip 分别需要一次性 Linux 主机和 systemd 主机。
- [x] 前端 typecheck、lint、84 项单测、生产构建和隔离 Playwright 8 项通过。
- [x] 订阅撤回回归覆盖请求前不支持协议拒绝、撤回后 Token 永久 410、节点缺少正向控制时 fail-closed、lease heartbeat/fencing 和部分失败记录。
- [x] r6 还包含地址池配额、逐周期最多删除同地区最早创建节点一台、每日一台排序重启、重启后状态/IP/健康读回、订阅创建与撤回、节点数量核对、IP/流量同步及服务器生命周期测试。
- [x] OpenAPI 确定性、固定 Xray 订阅格式、边界、秘密、skill、验收矩阵和 `git diff --check` 门禁通过。

门禁证据绑定到源码候选提交 `f2eac62d4d731c1f1ae4aba95191eb322bf8ecbd`，位于 `artifacts/acceptance/0.14.3/final-gates-20261107-r6/summary.tsv` 和 `backend-and-delivery.junit.xml`。证据使用本机专用 PostgreSQL/Redis、Fake/Stub provider、固定 Xray 二进制和隔离浏览器；不能证明真实 AWS、SSH 或生产可用性。

## 发布状态

- [x] 发布索引 `72705321685b4294d9128f626fff83f5ce572132` 已推送；annotated tag object `3aedbe34fc2725e5d4c7645883f918fca298b7a2` 已推送并 peeled 到发布索引。
- [x] GitHub Release `437560023` 已发布，非草稿/非预发布。三个远端 asset digest 与本地匹配：tar.gz `0a6108cfd5e98e8a924741ff61b1db2d2929f405b92d76704a81e245df3c4629`、manifest `4f4faf73f519c9c47a4accae33c713f8d4ed096886ff265a0863b6f7cf51f34a`、`SHA256SUMS` `40ecc63308d5975d3d861a3bf0e01660ef573d494ddb4499da39d0978567789e`。
- [x] main push Actions run `42370364174` 与 tag push runs `42371981253`/`42372069677` 均在 runner 启动前失败，0 steps；注解指向近期账户付款失败或消费限额需要提高。未更改账单设置，远端 CI 保持 blocked。

## 外部验收边界

- [ ] AWS 测试服务器创建/删除、SSH、动态 IP 与服务健康读回、真实订阅更新/撤回和云端流量采集仍未实机验证。
- [ ] 管理员首次 TOTP 绑定尚待账号持有人完成，CloudAccount 尚未在应用中配置/验证；不绕过 MFA 或由代理持有验证器/恢复码。没有 AWS 实例写入，费用 USD 0（预算授权上限 USD 1,000）。
- [ ] SWAS、真机 Shadowrocket、公网探测和生产发布未运行。

## 回退

应用可回到 `v0.14.2`，或分别对源码提交 `4cd7988844040a74c75157e5d03af66598aa094e` 和格式修正提交 `f2eac62d4d731c1f1ae4aba95191eb322bf8ecbd` 执行 `git revert`。本版本无新增数据库迁移；不得反向迁移或恢复已撤销 Token、凭据、安全事件或云操作状态。
