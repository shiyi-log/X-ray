# v0.14.0 发布清单

## 本地交付

- [x] 完整 `scripts/check-local.sh`：19 项门禁全部退出 0。
- [x] 后端/交付测试 `447 passed, 2 skipped`（449 total）；跳过项需要一次性 Linux 与 systemd 主机。
- [x] 前端 typecheck、lint、`84` 项单测、生产构建和 run-id 隔离 Playwright `8 passed`。
- [x] 节点配额、每日轮转、状态/IP/流量对账、节点数核对、订阅创建/撤回和独立生命周期测试已覆盖；新增多格式备用订阅缩容回归通过。
- [x] `git diff --check`、边界、秘密、skill、OpenAPI、迁移漂移和验收矩阵通过。

最终完整门禁证据位于 `artifacts/acceptance/0.14.0/final-gates-20261107-r10/`；r10 在源码候选 `c882ac03a29091825d4597b39bd753c3e70f7d18` 的干净工作树上运行，19/19 gates exit 0，JUnit 449 total、447 passed、2 skipped，前端单测 84 passed、Playwright 8 passed。每日重启成功游标由 identity `0007_dailyrestartsuccesscursor` nullable additive migration 保存；只有自动重启 operation 最终 SUCCEEDED 才前移，失败后下一计划日继续同一轮转位置，结果待对账时保持阻塞且不自动重放。每个地区每轮最多排队一台 `(created_at, pk)` 最早节点删除，超额节点按后续同步间隔逐步收敛。Operation 租约续期从取得行锁并确认 fence 仍有效后开始计时。两个跳过项要求一次性 Linux 与 systemd 主机。

## 发布读回

- [x] `main` 与注释标签 `v0.14.0` 已推送并回读：`main` 和 tag peeled commit 均为 `1c2a5ca78fbe809f4f5a21f7e6d6c358133d5b8d`。
- [x] GitHub Release `v0.14.0` 已创建为非草稿；安装器 tar.gz、manifest、`SHA256SUMS` 三项远端 SHA-256 与本地构建结果匹配。因 Release workflow 两次失败且没有 job steps，已按仓库脚本本地打包并手动创建 Release。
- [x] 最终源码候选、版本/tag peeled SHA、回退提交、远端 Release 资产、CI 阻断及 AWS 限制已记录在 `docs/version-record.md`、`docs/progress.md` 与 `tests/acceptance/matrix.json`。
- [ ] GitHub delivery-gates 远端成功：run `42305314710` 的第 2 次尝试失败且无 job steps；本地 r10 全量门禁通过。

## 外部验收边界

- [ ] 真实 AWS 测试服务器启动、停止、重启后的 IP/健康状态、订阅更新/撤回及精确资源回收；目前受绑定凭据无法解封阻塞。
- [ ] 真实 SWAS、SSH、公网探测、设备导入和生产验收。

当前真实 AWS 验收受阻：`root` profile 与数据库 Lightsail CloudAccount 的只读身份指纹一致（`sha256:4a0ef08458dd`），但应用密钥无法解封 CloudAccount 当前绑定的不可变凭据版本（AES-GCM authentication failed）。未使用 CLI 绕过应用授权，未创建云资源、未 SSH、未操作订阅，当前云费用为 USD 0；预算上限仍为用户授权的 USD 1,000。源码已有固定安装/健康探针运行时，但真实 bootstrap、Lightsail 防火墙和数据面仍无实机证据。

## 回退

应用代码以 `v0.13.0` 或本版本提交的 `git revert` 回退。不得反向迁移、恢复已撤销 Token/凭据、安全事件或云端操作结果；不覆盖测试数据库或历史验收记录。
