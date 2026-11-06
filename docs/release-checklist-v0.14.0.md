# v0.14.0 发布清单

## 本地交付

- [x] 完整 `scripts/check-local.sh`：19 项门禁全部退出 0。
- [x] 后端/交付测试 `443 passed, 2 skipped`（445 total）；跳过项需要一次性 Linux 与 systemd 主机。
- [x] 前端 typecheck、lint、`84` 项单测、生产构建和 run-id 隔离 Playwright `8 passed`。
- [x] 节点配额、每日轮转、状态/IP/流量对账、节点数核对、订阅创建/撤回和独立生命周期测试已覆盖；新增多格式备用订阅缩容回归通过。
- [x] `git diff --check`、边界、秘密、skill、OpenAPI、迁移漂移和验收矩阵通过。

完整门禁汇总见 [summary.tsv](../artifacts/acceptance/0.14.0/final-gates-20261107-r5/summary.tsv)，JUnit 报告与日志同目录。所有 19 项门禁退出码为 0，摘要中每个日志引用均指向本轮 `r5` 目录；旧候选证据保留。每个地区每轮最多提交一台最早节点删除，超额节点按同步间隔逐步收敛；每日最多提交一台轮转重启，失败或结果待对账时不自动重试。

## 发布读回

- [ ] `main`、注释标签 `v0.14.0`、Actions 和 GitHub Release 已推送后回读。
- [ ] 若 Release 已创建，远端资产及 SHA-256 已核对；若未创建，记录工作流状态和阻断原因。
- [ ] 最终版本提交、标签 peeled SHA、回退提交和远端状态已写入 `docs/version-record.md`、`docs/progress.md` 与 `tests/acceptance/matrix.json`。

## 外部验收边界

- [ ] 真实 AWS 测试服务器启动、停止、重启后的 IP/健康状态、订阅更新/撤回及精确资源回收；目前受绑定凭据无法解封阻塞。
- [ ] 真实 SWAS、SSH、公网探测、设备导入和生产验收。

当前真实 AWS 验收受阻：`root` profile 与数据库 Lightsail CloudAccount 的只读身份指纹一致（`sha256:4a0ef08458dd`），但应用密钥无法解封 CloudAccount 当前绑定的不可变凭据版本（AES-GCM authentication failed）。未使用 CLI 绕过应用授权，未创建云资源、未 SSH、未操作订阅，当前云费用为 USD 0；预算上限仍为用户授权的 USD 1,000。源码已有固定安装/健康探针运行时，但真实 bootstrap、Lightsail 防火墙和数据面仍无实机证据。

## 回退

应用代码以 `v0.13.0` 或本版本提交的 `git revert` 回退。不得反向迁移、恢复已撤销 Token/凭据、安全事件或云端操作结果；不覆盖测试数据库或历史验收记录。
