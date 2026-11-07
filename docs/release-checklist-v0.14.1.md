# v0.14.1 发布清单

## 本地验收

- [x] `scripts/check-local.sh` 在干净源码提交 `78bbcf31b0230f6f8d9a09396ae5f8cd64229e19` 上完成；19/19 门禁退出码为 0。
- [x] 后端与交付测试共 450 项：448 passed、2 skipped、0 failures/errors。跳过项需要一次性 Linux 主机和 systemd 主机。
- [x] 前端 typecheck、lint、84 项单测、生产构建与 run-id 隔离 Playwright 8 项通过。
- [x] 生命周期与自动化回归覆盖地区配额对齐、每日一台轮转重启、重启状态/IP/健康回读、状态/IP 与流量同步、节点数核对，以及节点创建/启动/停止/重启/删除和订阅签发/撤回。
- [x] 每个地区的缩容选择 `created_at` 最早且符合安全条件的服务器；每次同步每地区至多提交一台，遇到不安全目标会阻塞，不跳过它删除更新的服务器。
- [x] 新增 IP 更新后订阅发布部分失败回归：保存新地址后操作进入 `NEEDS_RECONCILIATION`；重试即使地址不再变化也会重新发布订阅，只有全部成功后操作才结束。
- [x] `git diff --check`、OpenAPI 确定性、固定 Xray 多格式解析、边界、秘密、skill 和验收矩阵均通过。

门禁证据位于 `artifacts/acceptance/0.14.1/final-gates-20261107-r2/`。真实云、SSH 与生产证据不由本地 Fake/Stub、容器或浏览器结果替代。

## 发布状态

- [ ] `main`、annotated `v0.14.1`、GitHub Release 与安装包资产尚待推送和远端 SHA-256 回读。
- [ ] GitHub delivery-gates / release workflow 尚无本版本运行证据；推送后按实际 run/job/step 状态记录，不猜测未分配 runner 的原因。

## 外部验收边界

- [ ] AWS 测试服务器生命周期、每日重启后的新 IP/健康状态、订阅更新/撤回、节点数与精确资源回收尚未实机验证。
- [ ] AWS 写入受阻：本地当前控制密钥无法通过认证解封测试库 CloudAccount 绑定的 credential version 1；现有证据无法区分主密钥漂移与密文/AAD 损坏。测试库没有已绑定 MFA，当前机器没有运行中的 X-ray 服务。未绕过应用鉴权使用 AWS CLI，未调用 AWS/SWAS 写入，未启动 SSH，费用 USD 0；本任务授权预算上限为 USD 1,000。
- [ ] SWAS、设备导入、公网探测与生产验收未运行。

## 回退

应用代码以 `v0.14.0` 或对本版本源码提交执行 `git revert` 回退。无新增数据库迁移；不得反向迁移或恢复撤销 Token、凭据、安全事件或云操作状态。
