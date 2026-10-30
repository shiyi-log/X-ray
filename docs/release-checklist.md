# v0.8 交付与发布检查表

本清单区分“交付包可复现”和“生产已经上线”。只有独立服务器、域名/TLS、真实
账号和恢复证据齐全后，生产矩阵项才可能从 `blocked` 改为 `passed`。

## 代码与版本

- [x] `VERSION`、backend OpenAPI、三个 frontend package 版本一致。
- [x] `backend/uv.lock`、`frontend/pnpm-lock.yaml` 无漂移，Vben commit/许可证已记录。
- [x] OpenAPI 连续生成两次无差异，生成的 TypeScript 无差异。
- [x] `git diff --check`、暂存文件清单、Gitleaks 和 Shop/archive 边界通过。
- [x] `CHANGELOG.md`、`docs/progress.md`、`docs/version-record.md` 已填写真实退出码和证据。
- [x] `tests/acceptance/matrix.json` 与 `VERSION` 一致并通过 validator。
- [x] GitHub Release 工作流会校验 `v${VERSION}`、上传安装器包和 `SHA256SUMS`。
- [x] 一键安装器与管理台热更新均固定到同一不可变版本标签。
- [ ] 匿名生产主机一键拉取：当前仓库为 private，需公开仓库或经授权的公开安装器托管。

## 本地和预发布门禁

- [ ] `./scripts/check-local.sh` 的 0.8.0 全量运行；0.7.0 的完整门禁作为上一版本基线保留。
- [x] 0.8.0 安装器发布包测试、前端单测、类型检查、构建、边界和验收矩阵校验通过。
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
`blocked`。本地门禁、提交和 `v0.8.0` 标签只证明交付包可定位、可重放、
可回退，不代表已上线。
