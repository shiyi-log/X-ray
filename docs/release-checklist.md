# v0.11.0 交付与发布检查表

本轮发布聚焦单订阅池、名称-only 订阅创建、随机 Token、无限策略、自动协议分配、服务器管理和地区额度改造。订阅聚焦测试、前端订阅检查、类型、定向 Lint、边界、验收矩阵和差异检查已通过；共享测试库完整套件复跑因残留连接与缺失 `SecurityState` 保持 `blocked`，不删除或重建共享测试库。真实 AWS/SWAS、SSH、生产 TLS、生产切换、设备和完整浏览器 E2E 仍为 `not-run` 或 `blocked`。

## v0.11.0 当前状态

- [x] `VERSION`、backend OpenAPI、backend/frontend package 版本同步为 `0.11.0`。
- [x] `CHANGELOG.md`、`docs/progress.md`、`docs/version-record.md` 和验收矩阵已更新。
- [x] 订阅后端聚焦测试 `36 passed`；前端订阅/交付测试 `7 passed`；vue-tsc、定向 ESLint、边界、验收矩阵和 `git diff --check` 通过。
- [x] 9527/9528 当前本地服务由本工作树监听，readiness、登录页和本地一键登录探针均 HTTP 200。
- [ ] 完整 backend/installer 全量门禁：共享测试库状态阻塞，清洁专用库证据沿用前序记录。
- [ ] 真实 AWS/SWAS、SSH、公网探测、生产部署、生产 TLS、设备验收和完整浏览器 E2E：本版本未运行。
- [ ] GitHub Release：待 `v0.11.0` 标签和安装器资产完成后回填不可变 SHA-256 证据。

## Historical v0.9.0 checklist

本清单区分“交付包可复现”和“生产已经上线”。只有独立服务器、域名/TLS、真实
账号和恢复证据齐全后，生产矩阵项才可能从 `blocked` 改为 `passed`。

## 代码与版本

- [x] `VERSION`、backend OpenAPI、三个 frontend package 版本一致。
- [x] `backend/uv.lock`、`frontend/pnpm-lock.yaml` 无漂移，Vben commit/许可证已记录。
- [x] OpenAPI 连续生成两次无差异，生成的 TypeScript 无差异。
- [x] `git diff --check`、暂存文件清单和 Shop/archive 边界通过。
- [ ] Gitleaks 无新增命中：当前扫描仍报告 2 个既有历史台账命中，未输出匹配内容。
- [x] `CHANGELOG.md`、`docs/progress.md`、`docs/version-record.md` 已填写真实退出码和证据。
- [x] `tests/acceptance/matrix.json` 与 `VERSION` 一致并通过 validator。
- [x] GitHub Release 工作流会校验 `v${VERSION}`、上传安装器包和 `SHA256SUMS`。
- [x] 一键安装器与管理台热更新均固定到同一不可变版本标签。
- [x] `v0.9.0` 已推送并创建正式 GitHub Release；三个资产的远端 SHA-256 与本地包匹配。
- [ ] 匿名生产主机一键拉取：当前仓库为 private，需公开仓库或经授权的公开安装器托管。

## 本地和预发布门禁

- [ ] `./scripts/check-local.sh` 的 0.9.0 全量运行；本轮使用分项门禁并保留 0.8.0 作为上一版本基线。
- [x] 0.9.0 安装器发布包测试、前端 65 项单测、类型检查、Lint、构建、后端 316 项测试、Chrome E2E、边界和验收矩阵校验通过。
- [x] production/staging Compose config 通过，只有 gateway 发布端口。
- [x] backend/frontend 使用固定非 root 用户；backup-tools 由包装器强制调用方 UID:GID；运行时只读、丢弃 capabilities 且无秘密/archive。
- [x] 固定 Xray 五协议、四订阅格式、强制撤销和真实浏览器全流程通过。
- [x] 加密 `pg_dump -> age -> pg_restore` 在新 `xray_restore_*` 数据库完成。
- [x] 恢复后立即 `MAINTENANCE`，旧 Token 不复活，旧 worker fence 被拒绝。
- [x] 本地 RPO/RTO 观测和 security ledger reconciliation 已脱敏保存。

## 生产前置条件

- [ ] 独立 Debian 12 服务器、私有管理入口、公开订阅域名和有效 TLS 已提供。
- [ ] 数据库角色、Docker secrets、离机 age 恢复密钥和主密钥托管已双人复核。
- [ ] AWS/SWAS 授权单包含账号、区域、套餐/镜像、预算、TTL 和逐项危险动作授权。
- [ ] 发布前加密备份已离机验证，安全账本无缺口，worker 已 drain。
- [ ] 生产 backup manifest、恢复 receipt 和 credential rotation receipt 已脱敏离机保存。
- [ ] 生产健康、TLS、订阅 no-store、默认拒绝、备份和隔离恢复均有外部证据。

## 发布与回退

- [ ] 发布只使用已验证不可变镜像摘要和兼容的 expand/contract 迁移。
- [x] 应用回退只切换已验证旧镜像，不恢复数据库、撤销记录、Token tombstone、云结果或旧凭据。
- [x] 恢复目标必须是新隔离数据库并保持 `MAINTENANCE`；人工复开前完成审计追平、撤销对账、全量凭据轮换及旧凭据拒绝验证。
- [x] 阶段提交和注释标签存在；代码历史通过 `git revert` 或阶段标签回退，禁止硬重置和强推。

## 发布判定

生产服务器、TLS、真实双云授权和生产恢复证据当前缺失，因此生产发布保持
`blocked`。本地门禁、提交和 `v0.9.0` 标签只证明交付包可定位、可重放、
可回退，不代表已上线。
