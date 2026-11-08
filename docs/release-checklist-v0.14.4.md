# v0.14.4 发布清单

## 本地验收

- [x] `VERSION`、后端/前端包、OpenAPI、Playwright 证据路径和安装器默认标签均为 `0.14.4`。
- [x] `test_daily_restart_health_failure_invalidates_stale_subscription_revision` 保留真实 `Publisher`，验证健康失败后旧 revision 不可用、没有新 revision、公开订阅返回 `503` 与 `no-store`。
- [x] 单独覆盖节点创建、停止、启动、重启、删除；地址池缺额补齐、超额时每周期删除一台最早创建的节点；每日排序轮转；状态/IP/流量同步及订阅节点数量核对。
- [x] 在发布源码候选上运行 `scripts/check-local.sh`，记录 19 项门禁、JUnit、前端单测和 Playwright 的准确计数及证据路径。最终 r2 为 19/19；后端 507 passed、2 skipped，前端 84 passed，Playwright 8 passed。r1 因磁盘空间不足在前端镜像构建阶段失败；r2 复用了现有 0.14.3 前端和 backup-tools 镜像，精确 0.14.4 镜像构建留待候选 CI。
- [x] acceptance validator、Shop/archive 边界、全历史和候选差异秘密扫描、skill 校验和 `git diff --check` 通过。全历史 Gitleaks 扫描 123 个提交；另使用 Gitleaks 8.24.3 对完整暂存候选差异（含 r1/r2 摘要与 JUnit）执行红acted stdin 扫描，退出码 0。

## 公开发布

- [ ] 推送经过本地门禁验证的 `main` 候选，并确认 GitHub Actions CI 成功。
- [ ] 在已验证的 `main` 候选上创建 annotated `v0.14.4` 标签，手动运行 Release workflow。
- [ ] 回读正式 GitHub Release、标签 peeled commit，以及 tar.gz、manifest、`SHA256SUMS` 的远端摘要。

## 外部验收边界

- [ ] X-ray 应用的 AWS 节点创建、SSH、真实动态 IP/健康读回、订阅创建/撤回、流量统计仍需真实 CloudAccount 与 MFA 前置；Fake/Stub 和本地容器不替代这些验收。
- [ ] 本阶段未创建应用测试服务器。专用 CI runner 的 AWS 资源仍运行并持续计费；本清单不把其费用记为零。
- [ ] SWAS、真机 Shadowrocket、公网探测和生产部署未运行。

## 回退

应用回退使用 `v0.14.3` 或对本阶段提交执行 `git revert`。不反向迁移，不恢复已撤销 Token、凭据、安全事件或云操作状态；保留公开标签和 Release 作为审计记录。
