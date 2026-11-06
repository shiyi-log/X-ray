# v0.13.0 交付与发布检查表

本版本增加地址池配额自动对齐、每日轮转重启、定时状态/IP/流量同步及订阅节点数量核对。自动创建仅完成云实例预留；安装、SSH 信任、健康确认和首次订阅发布尚未打通。真实 AWS/SWAS、SSH、生产 TLS、生产切换、设备验收和云端端到端流程按验收矩阵保持阻塞或未运行。

## v0.13.0 当前状态

- [x] `VERSION`、后端/前端包、OpenAPI、验收矩阵和安装器标签更新为 `0.13.0`。
- [x] 最新工作树的 19 项本地 delivery gate 均 exit 0；`artifacts/acceptance/0.13.0/final-gates-2/summary.tsv` 与 JUnit 记录后端 `417 passed, 2 skipped`（419 tests，0 failures，0 errors）、前端 `82 passed`、浏览器断言 `8 passed`。旧 `artifacts/acceptance/0.13.0/gates/` 的 `402 passed, 2 skipped` 仅保留为历史候选证据，不与本轮计数混用。
- [x] OpenAPI 确定性、固定 Xray、四种订阅格式、安装器/交付测试、类型检查、Lint、构建、边界、秘密、skill 和验收矩阵门禁均记录为 exit 0；两个 Linux/systemd 专用集成测试因环境要求跳过。
- [x] E2E 已在 run-id 隔离的 disposable PostgreSQL/Redis 栈复跑：数据库护栏 6 passed，package-level Playwright wrapper 8 passed，teardown 清理本轮容器；历史 55433 `xray_test` 清库事故仍保留在验收矩阵和台账中，未覆盖或恢复旧数据。
- [x] 每日重启按配置的 IANA 时区轮转，每个本地日最多排队一台；调度时即记账，因此云重启或健康探针失败后当天不会自动重试，失败操作须人工重试或等待下一本地日。
- [ ] GitHub 当前提交的 delivery-gates/Release 结果及 `v0.13.0` 远端资产摘要未回读；不得用历史版本 Release 代替。
- [ ] 真实 AWS 端到端验收阻塞：创建链路没有安装与健康确认；AWS 测试前还需完成新实例入站规则的安全收敛。
- [ ] 自动补池尚未贯通 SSH 主机身份批准、安装、协议/入站规则初始化、健康确认和首次订阅发布，当前仅到 `PROVISIONED`。
- [ ] SSH、公网探测、生产部署、生产 TLS、设备验收和生产切换未运行；生产发布保持 `blocked`。

## 发布与回退

- [ ] 应用回退使用 `v0.12.2` 或对本轮提交执行 `git revert`；不反向迁移、不恢复 Token tombstone、安全事件、撤销凭据或云端状态。

---

## v0.12.2 候选记录

- [x] `VERSION`、backend OpenAPI、frontend package、验收矩阵和安装器默认标签同步为 `0.12.2`。
- [x] Ruff 0.13.1 全仓库检查通过；补充订阅撤销操作中文标签的前端回归断言。
- [ ] GitHub delivery-gates 与 Release workflow 结果待对应版本发布后回读。
- [ ] 真实 AWS/SWAS、SSH、公网探测、生产部署、生产 TLS、设备验收和完整浏览器 E2E 未运行。

---

## v0.12.1 发布记录

- [x] GitHub `v0.12.1` 正式非草稿 Release 已发布，Release workflow run `41423911493` 成功；标签指向提交 `9f1a10782c2b0c88163e83d83753c4ad271d9511`。
- [x] 远端 `SHA256SUMS`、manifest、tar.gz 资产已上传并经后续读取校验；摘要记录在 `docs/version-record.md`。
- [x] 冻结依赖安装修复通过；delivery-gates run `41423915567` 进入完整本地门禁后，在 Ruff 阶段因 25 项诊断失败，后续门禁未运行。v0.12.2 修复这些诊断。
- [ ] 真实 AWS/SWAS、SSH、公网探测、生产部署、生产 TLS、设备验收和完整浏览器 E2E：本版本未运行。

---

## v0.12.0 发布记录

- [x] GitHub `v0.12.0` 正式非草稿 Release 已发布；远端 `main` 和注释标签指向 `7694984795f5a501b3f390aa9648dd7ef3d18087`。
- [x] Release workflow 成功；远端 `SHA256SUMS`、manifest、tar.gz 的资产 SHA-256 分别为 `9d2fea262771ad906c5290036f46b8fc5682c4b2f8c89ea58d3e36b587a15d22`、`050f6bc96b68246e972ffb33d6bbbace3ba93ffec12d62248798fd38da162758`、`4693e42af1fa776c1e68f306c7c0f8898ef81ddab2124d57a3259611a0c0aa8e`；远端校验文件通过。
- [x] GitHub delivery-gates run `41421735958` 在 `Install locked dependencies` 失败，原因为 catalog 与锁文件不一致；依赖安装后的检查步骤未运行。v0.12.1 修订此锁文件问题。

---

以下为历史 `v0.11.0` 发布检查记录。

本轮发布聚焦单订阅池、名称-only 订阅创建、随机 Token、无限策略、自动协议分配、服务器管理和地区额度改造。订阅聚焦测试、前端订阅检查、类型、定向 Lint、边界、验收矩阵和差异检查已通过；共享测试库完整套件复跑因残留连接与缺失 `SecurityState` 保持 `blocked`，不删除或重建共享测试库。真实 AWS/SWAS、SSH、生产 TLS、生产切换、设备和完整浏览器 E2E 仍为 `not-run` 或 `blocked`。

## v0.11.0 当前状态

- [x] `VERSION`、backend OpenAPI、backend/frontend package 版本同步为 `0.11.0`。
- [x] `CHANGELOG.md`、`docs/progress.md`、`docs/version-record.md` 和验收矩阵已更新。
- [x] 订阅后端聚焦测试 `36 passed`；前端订阅/交付测试 `7 passed`；vue-tsc、定向 ESLint、边界、验收矩阵和 `git diff --check` 通过。
- [x] 9527/9528 当前本地服务由本工作树监听，readiness、登录页和本地一键登录探针均 HTTP 200。
- [ ] 完整 backend/installer 全量门禁：共享测试库状态阻塞，清洁专用库证据沿用前序记录。
- [ ] 真实 AWS/SWAS、SSH、公网探测、生产部署、生产 TLS、设备验收和完整浏览器 E2E：本版本未运行。
- [x] GitHub Release：`v0.11.0` 正式非草稿 Release 已发布；远端 `SHA256SUMS`、manifest、tar.gz 摘要分别为 `14853de2e00820830084ef808421de70f5b581f745f6657bc905835157934eb2`、`f84284e6ef22e820b3ffaf91b3cdcc34f10fc12484c08ae9bced6621186fadf0`、`20a2e91662e7330514bbbd46a81ad46558580cbd6f6b4bf97b569232c293b6af`，远端校验文件通过。

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
