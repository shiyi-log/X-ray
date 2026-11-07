# v0.14.1 发布清单

## 本地验收

- [x] `scripts/check-local.sh` 在干净源码提交 `78bbcf31b0230f6f8d9a09396ae5f8cd64229e19` 上完成；19/19 门禁退出码为 0。
- [x] 后端与交付测试共 450 项：448 passed、2 skipped、0 failures/errors。跳过项需要一次性 Linux 主机和 systemd 主机。
- [x] 前端 typecheck、lint、84 项单测、生产构建与 run-id 隔离 Playwright 8 项通过。
- [x] 生命周期与自动化回归覆盖地区配额对齐、每日一台轮转重启、重启状态/IP/健康回读、状态/IP 与流量同步、节点数核对，以及节点创建/启动/停止/重启/删除和订阅签发/撤回。
- [x] 人工将某地区配额从 4 调为 3 时，在该地区选择 `created_at` 最早且符合安全条件的一台服务器；每次同步每地区至多删除一台，遇到不安全目标会阻塞，不跳过它删除更新的服务器。
- [x] 新增 IP 更新后订阅发布部分失败回归：保存新地址后操作进入 `NEEDS_RECONCILIATION`；重试即使地址不再变化也会重新发布订阅，只有全部成功后操作才结束。
- [x] `git diff --check`、OpenAPI 确定性、固定 Xray 多格式解析、边界、秘密、skill 和验收矩阵均通过。

门禁证据位于 `artifacts/acceptance/0.14.1/final-gates-20261107-r2/`。真实云、SSH 与生产证据不由本地 Fake/Stub、容器或浏览器结果替代。

## 发布状态

- [x] `main` 已推送到 `33d36785e76ae00dc83652ee7f6ace0e56c18c96`；annotated `v0.14.1` tag object `f20546a4a55c61753a9ae3562941765fd9335ad3` peeled 到同一提交。
- [x] GitHub Release `v0.14.1`（Release id `437350564`）为非草稿、非预发布；已读回并核对 `SHA256SUMS`、manifest、tar.gz 三项资产的 SHA-256 均与本地构建匹配。
- [x] 已核对 delivery-gates run `42341132257` 和 Release run `42341132078`；两个 job 均 `runner_id=0`、`steps=[]`。根因未知，远端 CI 状态保持 blocked，不记为通过。

## 外部验收边界

- [ ] AWS 测试服务器生命周期、每日重启后的新 IP/健康状态、订阅更新/撤回、节点数与精确资源回收尚未实机验证。
- [x] 独立本地验收环境已在已登记 loopback 端口启动：前端 `http://127.0.0.1:9538/`、后端 `9537`、PostgreSQL `55433`、Redis `56380`，均使用独立 Compose 项目/卷；本地健康检查 HTTP 200，一键登录关闭，TOTP 旁路关闭。
- [ ] AWS 写入仍受阻：原 `xray-test` 库的 CloudAccount credential version 1 在只读复核中仍无法通过当前控制密钥的 AES-GCM/AAD 认证；无法区分主密钥漂移与密文/AAD 损坏。新隔离库管理员已初始化，但尚未绑定 MFA，且没有 CloudAccount/节点。需管理员在上述本地页面完成 MFA，并在 Cloud Accounts 表单录入/验证 AWS 测试凭据；不要在聊天中发送云凭据。未调用 AWS/SWAS 写入、未启动 SSH，费用 USD 0；本任务授权预算上限 USD 1,000。
- [ ] SWAS、设备导入、公网探测与生产验收未运行。

## 回退

应用代码以 `v0.14.0` 或对本版本源码提交执行 `git revert` 回退。无新增数据库迁移；不得反向迁移或恢复撤销 Token、凭据、安全事件或云操作状态。
