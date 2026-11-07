# v0.14.2 发布清单

## 本地验收

- [x] 在干净源码提交 `c48cddbba5bbef777590568029f49fa02c479dc9` 上运行 `scripts/check-local.sh`；19/19 门禁退出码为 0。
- [x] 后端与交付测试共 452 项：450 passed、2 skipped、0 failures/errors。两个 skip 分别需要一次性 Linux 主机和 systemd 主机。
- [x] 前端 typecheck、lint、84 项单测、生产构建和 run-id 隔离 Playwright 8 项通过。
- [x] 4 台降至配额 2 的回归覆盖每地区每轮最多提交一项删除；首项仍在途时不重复或切换目标；确认首台释放配额后，下一轮选择第二早节点。
- [x] 自动化测试覆盖按缺额创建、逐日单台轮转重启、成功游标、失败/健康阻断、配置和 step-up；服务器创建、启动、停止、重启、删除各有生命周期回归。
- [x] 生命周期和订阅回归覆盖重启后状态/IP/健康读回、动态 IP 更新后重新发布订阅、地址保存后订阅部分失败重试、订阅创建/多格式发布/节点数量核对、Token 与单节点撤回、确认云端资源不存在后才释放配额。
- [x] 固定 Xray 二进制覆盖 VLESS 与 SOCKS5 服务端流量采集；覆盖 SOCKS5 用户映射、跨协议合计、重复 sequence 幂等及身份冲突 fail-closed。
- [x] OpenAPI 确定性、固定 Xray 订阅格式、边界、秘密、skill、验收矩阵和 `git diff --check` 门禁通过。

门禁证据绑定到源码提交 `c48cddbba5bbef777590568029f49fa02c479dc9`，位于 `artifacts/acceptance/0.14.2/final-gates-20261107-r5/summary.tsv` 和 `backend-and-delivery.junit.xml`。这些是本机专用数据库/Redis、Fake/Stub provider、固定本地 Xray 二进制和浏览器证据，不代表真实 AWS 或生产通过。

## 发布状态

- [x] 源码、缩容回归、r5 摘要/JUnit 与发布索引已推送至 `main`；远端主线为 `990b3f858725966465f4ccf19ce9a9310445a755`。
- [x] `v0.14.2` annotated tag object `cdc2c18a1ea6e3392fb307690c1fed0aaf8f4275` 已推送并 peeled 到 `990b3f858725966465f4ccf19ce9a9310445a755`；GitHub Release id `437428455` 已发布，为非草稿、非预发布。
- [x] `SHA256SUMS`、manifest、tar.gz 三项远端 asset digest 与本地构建匹配：`ec64ee66c7a4af10fe232b17138ea02289df442b705532f5b313c814856f8589`、`36914698febfe38690a5907ba33507c941997e411f75079e794b7a9c49af12df`、`495aca7d78d28dacb10e290ea756a67e637b6edafc5b77359f9d484b92e9e371`。
- [x] main push 的 delivery-gates run `42352685572` 失败；verify job `128344001970` 没有执行步骤。根因未知，远端 CI 保持 blocked，不记作通过。
- [x] tag push 的 delivery-gates `42353586340` 与 release workflow `42353586370` 均在 0 steps 后失败；因此按本地已校验包手动创建 Release，远端 CI 仍 blocked。

## 外部验收边界

- [ ] AWS 测试服务器创建/删除、启动/停止/重启、每日调度、重启后公网 IP 与服务健康读回、真实订阅更新/撤回及流量采集尚未实机验证。
- [x] 独立本地验收环境保留运行：前端 `http://127.0.0.1:9538/`，后端 readiness `9537`，PostgreSQL `55433`，Redis `56380`；未停止服务或删除数据卷。
- [ ] 管理员尚未在隔离应用完成 TOTP，应用 CloudAccount 数为 0；AWS CLI 身份预检成功但尚未通过 X-ray 的 MFA/CloudAccount/Operation 正常流程。没有绕过应用安全流程直接写 AWS；未创建测试服务器，费用 USD 0（预算授权上限 USD 1,000）。
- [ ] SWAS、SSH、真机 Shadowrocket、公网探测和生产发布未运行。

## 回退

应用代码可回到 `v0.14.1`，或分别对源码提交 `d6d6550ed76c9a5a560d7ddac04b592188450770` 和回归提交 `c48cddbba5bbef777590568029f49fa02c479dc9` 执行 `git revert`。本版本无新增数据库迁移；不得反向迁移或恢复已撤销 Token、凭据、安全事件或云操作状态。
