# 交付与发布检查表

## v0.14.12 当前状态（2026-11-16）

生产已升级为 0.14.12，源码与 annotated v0.14.12 固定在 34fff784ecbff0d82d0ceda17846984bb0a2c04d。Shadowrocket 现有订阅已刷新，四条名称均以前置实际 IP 标识；IPv6 使用方括号。真实截图和结果位于 artifacts/acceptance/0.14.12/real-use-20261116/shadowrocket-ip-labels.png 及 shadowrocket-ip-labels-acceptance.json。

- [x] 本地候选19/19 gate、prefix focused19 passed；精确源码远端CI43793611925 success，19/19 gate，后端691 passed/1 Linux skip、前端118、E2E8。
- [x] 正式Release446631467与workflow43808611452 success；三个资产独立下载、SHA256SUMS、GitHubdigest和内外manifest一致。
- [x] backend/frontend/backup-tools linux/amd64不可变镜像、HTTP manifest摘要、platform/config digest和revision核验；root可信source snapshot/catalog。
- [x] 正常管理员login/CSRF/recent step-up/UUID升级，job5a79fc8d-97cc-4c89-8776-15c3ffdde457 SUCCEEDED/COMPLETE；十服务running六healthy，TLS200/200/401/404，备份checksum有效。
- [x] B正常重新发布revision4且token epoch不变；小火箭更新现有订阅，四个IP均可见。
- [x] fixed restore真实隔离恢复0、已有目标库拒绝1、MAINTENANCE读回0；恢复环境未复开。
- [ ] 全节点验收仍failed：N2 IPv4超时。用户已回复“仅完成 IP 显示，保留连接失败记录”，本轮以IP显示交付收尾；原云写窗口未续授，不执行N2停止/启动、换动态IPv4或节点删除。
- [ ] A410/B503原始token完整恢复验收仍not-run，不能用shell回归或无token的维护屏障检查替代。
- [ ] 逐资源最终费用unknown，未声称最终账单或immutable offsite storage通过。

| 节点 | 发布地址 | 本机刷新后逐项测试 |
| --- | --- | --- |
| N2 | 46.137.228.67:8388 | **failed：超时** |
| N2 | [2406:da18:1e16:f200:f22:8595:ebaf:81ee]:8388 | passed：87ms；此前网页/视频成功 |
| N1 | 13.212.118.138:8388 | passed：88ms；此前客户端SOCKS Google204 |
| N1 | [2406:da18:1e16:f200:e076:f3d5:e3eb:d72]:8388 | passed：90ms；此前网页/视频成功 |

IP显示交付通过，全节点可用性为3/4、整体failed；不得删除N1或用单节点替代。客户端保留N2 IPv6选中、隧道开启。原自然48小时/iPhone/蜂窝验收由用户改为本机单次快速验收，不恢复旧要求。应用回退使用0.14.11验证镜像/config及history/5a79fc8d-97cc-4c89-8776-15c3ffdde457.env；不恢复撤销Token、凭据、安全或云状态。

## v0.14.11 历史状态（2026-11-15）

当时线上与正式标签源码为 `d037899d15bcdb5a6f27d9255b27270be0a5d6fe`。
证据目录：`artifacts/acceptance/0.14.11/production-release-20261115/`。

- [x] 精确源码 CI `43690632106`，19/19 gate exit 0；后端667 passed、1 skipped，前端117、E2E8。
- [x] annotated v0.14.11及正式Release445892040；三项资产独立下载，GitHub digest/SHA256SUMS/内外manifest一致。
- [x] 正常公网登录、step-up与前端在线升级0.14.10→0.14.11，任务51b28c61-b092-4092-b318-72f5a3eae5b9 SUCCEEDED/COMPLETE，刷新会话保持。
- [x] 订阅列表“订阅链接”、统一和小火箭两个可见复制按钮；真实Chrome完整剪贴板匹配，关闭后交付清空；验证后草稿保留且不重复创建。
- [x] 显式轮换提示旧链接立即失效；轮换及撤回GET/HEAD410，缺preview409，profile撤回Operation成功，测试profile已REVOKED，原2222未签发。
- [x] 十服务running、六healthy；严格TLS管理200/订阅健康200/匿名system401/订阅域管理404。加密备份checksum有效，回退文件及安全快照存在；本轮未再次解密备份，先前隔离恢复证据保留。
- [x] 本轮无AWS写；自动补池、每日重启、状态同步和流量同步开关均关闭，无非终态Operation、无占配额节点。本轮保留池expected1、assigned/ready/published0的差异显示，不擅改用户配置。
- [x] 既有真实Lightsail补齐、计划重启、新IP/健康/订阅写回、流量、节点数、撤回正控和自动缩容验收见下方0.14.10历史证据，本轮不重复建云资源。
- [x] 预算核对已完成：已知组件USD124.75771355652、附假设审慎评估额度USD250；最新单节点预算USD25，报告列明预留与限制，未将评估写成无条件最终账单硬上界。
- [ ] 逐资源最终账单仍unknown；功能完成不额外等待最终发票。
- [ ] 一次性Linux/systemd集成、SWAS及Shadowrocket iOS真机未运行，不以订阅格式或Lightsail证据冒充。

应用回退使用 `/var/lib/xray/upgrade/history/51b28c61-b092-4092-b318-72f5a3eae5b9.env`，
源码回退使用v0.14.10或git revert；不得恢复已撤销、安全或云状态。AWS写授权已过期。

---

## v0.14.10 历史验收状态（2026-11-14）

本节仅描述该版本当时的验收结果。精确源码为
`8f54917c0504ce3764897f44dae70818cc8aa75d`，当前证据见
`artifacts/acceptance/0.14.10/production-release-20261114/` 和验收矩阵。

- [x] 版本元数据、OpenAPI、安装器默认版本、CHANGELOG 与发布索引一致。
- [x] 精确源码 Delivery Gates run `43497335886` 成功：19 项门禁 exit 0，后端/交付 666 passed、1 skipped，前端 97 passed，浏览器 E2E 8 passed。
- [x] annotated `v0.14.10` 和正式 Release `444685736` 已发布；三项资产独立下载的 SHA-256、GitHub digest、SHA256SUMS 和包内外 manifest 均一致。
- [x] 授权生产主机已使用不可变镜像上线 0.14.10，管理入口、公开订阅域名与严格验证的 TLS 可用，证书续期 dry-run 和 renewal wrapper 成功。
- [x] 前端「系统设置 → 版本更新 → 在线升级」真实完成 0.14.9 → 0.14.10；近期身份验证、提交、备份/排空/迁移/健康检查、重连与刷新后会话保持均有证据，任务 `SUCCEEDED / COMPLETE`。
- [x] 分配保存、桌面三列/手机单列、刷新持久化通过；生产 allocation 表的最小 DELETE 权限有实际角色回归。
- [x] 一台授权 Lightsail 节点自动补齐至 READY/HEALTHY，计划停止后启动、新 IP/状态/健康/订阅写回、流量采集、数量核对、A profile 撤回/B 正向控制及自动缩容删除通过；最终测试资源、配额与订阅节点计数均为零。
- [x] 四种支持格式含 Shadowrocket 均可读取且新地址匹配；通过节点访问 Google 的 TLS 校验和 HTTP 200 已验证，读取结果为部分响应，不作完整下载或 iOS 真机声明。
- [x] 加密备份独立离机保存，解密/校验/pg_restore 列表验证成功，隔离恢复确认 MAINTENANCE；回退只切换历史镜像/config，不恢复已撤销、安全或云状态。
- [ ] 逐资源最终账单尚未提供可归因金额，保持 unknown；不把空费用组或账号估算解释为资源最终费用。
- [ ] `test_dynamic_service_user_can_read_root_only_configuration` 需要一次性 Linux/systemd 主机，当前 CI 明确跳过，未声称该项通过。
- [ ] SWAS 与 Shadowrocket iOS 真机未运行；这些证据不由 Lightsail/订阅格式验收替代。

应用回退依据 root 升级历史 `013dcb3b-6c04-417d-b081-30677a7df144.env`
中的上一组 0.14.9 镜像/config；源码使用 `git revert`。AWS 写窗口已于
`2026-11-14T03:59:00+08:00` 截止，不得沿用该窗口新建或变更云资源。

---

## v0.13.0 历史交付记录

本版本增加地址池配额自动对齐、每日轮转重启、定时状态/IP/流量同步及订阅节点数量核对。自动创建仅完成云实例预留；安装、SSH 信任、健康确认和首次订阅发布尚未打通。真实 AWS/SWAS、SSH、生产 TLS、生产切换、设备验收和云端端到端流程按验收矩阵保持阻塞或未运行。

## v0.13.0 当时状态

- [x] `VERSION`、后端/前端包、OpenAPI、验收矩阵和安装器标签更新为 `0.13.0`。
- [x] 最新工作树的 19 项本地 delivery gate 均 exit 0；`artifacts/acceptance/0.13.0/final-gates-2/summary.tsv` 与 JUnit 记录后端 `417 passed, 2 skipped`（419 tests，0 failures，0 errors）、前端 `82 passed`、浏览器断言 `8 passed`。旧 `artifacts/acceptance/0.13.0/gates/` 的 `402 passed, 2 skipped` 仅保留为历史候选证据，不与本轮计数混用。
- [x] OpenAPI 确定性、固定 Xray、四种订阅格式、安装器/交付测试、类型检查、Lint、构建、边界、秘密、skill 和验收矩阵门禁均记录为 exit 0；两个 Linux/systemd 专用集成测试因环境要求跳过。
- [x] E2E 已在 run-id 隔离的 disposable PostgreSQL/Redis 栈复跑：数据库护栏 6 passed，package-level Playwright wrapper 8 passed，teardown 清理本轮容器；历史 55433 `xray_test` 清库事故仍保留在验收矩阵和台账中，未覆盖或恢复旧数据。
- [x] 每日重启按配置的 IANA 时区轮转，每个本地日最多排队一台；调度时即记账，因此云重启或健康探针失败后当天不会自动重试，失败操作须人工重试或等待下一本地日。
- [ ] GitHub 当前提交的 delivery-gates（run `42187129135`）和 Release workflow（run `42187198168`）均在无步骤执行的情况下 `failure`；`v0.13.0` 标签已推送但 GitHub Release API 返回 404、无远端资产，不能将远端发布标为通过。
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
