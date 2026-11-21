# X-ray 项目约定

从 2026-11-17 起，活跃应用源码切换为 MHSanaei/3x-ui v3.11.0，固定上游提交 `c621ba9014a6aa21fd7c9ecf45655e44e24ebf13`。依据是用户明确要求放弃现有代码并指定 `MHSanaei/3x-ui`，同时限定首阶段为导入底座并跑本地构建/测试。该决定只界定新代码基线，不授权云操作、部署、迁移旧数据库或复刻旧功能。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `AGENTS.md` | 当前项目硬边界和代理最小入口 |
| 本文件 | 当前源码、数据、测试和版本约定 |
| `skills/xray-manager/SKILL.md` | X-ray 任务执行入口 |
| `docs/project-ledger.md` | 追加式操作审计 |
| `docs/progress.md` | 当前阶段门禁、证据和状态 |
| `UPSTREAM.json` | 版本、提交及源码归档SHA256 |
| `artifacts/acceptance/3x-ui-rebase-20261117/replacement-manifest.json` | 导入/移除逐文件摘要和过滤清单 |

旧项目的文档、版本号、矩阵、验收产物和在此约定生效前的 ledger/progress 条目都是历史，不代表 3x-ui 当前功能或生产状态。历史记录只追加更正，不重排、不伪装旧验收为新系统验收。

## 上游和范围

- 固定的活跃底座是上游发布 `v3.11.0` 的不可变提交。原始导入文件必须匹配逐文件清单。依赖必须使用原始 Go/npm 锁定文件。
- 当前构成是 Go 1.27.3、CGO SQLite/PostgreSQL 后端和 Node 26 / npm 11 的 React/TypeScript 页面。不能继续把 Django、Celery、Vben、pnpm、Redis 或旧专属端口写成当前运行结构。
- 首阶段不自创应用功能。首次定制前必须把纯上游哈希基线改造成“受审查补丁 + 来源锁定”策略，并重新记录授权、测试和回退。不能绕过检查后再无记录地重算清单。
- 任何上游提取、导入、构建和发布输入只能来自清单。`archive/`、Shop、`vue-shop-admin`、`shop-xray-installer` 与本机忽略数据不属于输入。
- 保留上游 GPLv3、版权、README、锁文件和第三方声明。旧自有实现的 AGPL 声明、Vben MIT 来源与旧许可证只适用于其历史提交；不能据此改写当前上游许可。

## 安全和运行边界

- 当前应用功能不得被描述为具备旧 Django 系统的 AWS 资源分配、二次认证、逐目标预览、审计 Outbox、撤销墓碑、恢复维护屏障、订阅池或在线升级能力，除非后续逐项实现、审计并测试。
- 上游首次启动会输出默认管理员凭据。首启路径完成交付和日志适配前，不要初始化或启动正式面板；构建测试不得运行上游安装器。
- 生产环境首次启动、TLS、认证配置和 Xray/MTG/Geo 数据必须单独锁定和验收。构建通过不等于代理数据面通过。
- 本地应用测试使用新建临时 SQLite，不得复用旧 `runtime/`、`data/`、备份或任何旧数据库。只有任务明示批准后才连接独立 PostgreSQL；不把旧 PostgreSQL/Redis Compose 当作新底座依赖。
- Go/Xray/浏览器测试可能创建临时监听。宿主运行服务前查共享端口登记和 listener，使用登记范围及 portctl 管理。测试监听优先置于不发布宿主端口的隔离容器；不因端口冲突停止或复用其他服务。
- 真实 AWS/SWAS 写入、SSH、公网探测、生产主机、删除、静态 IP 释放、真实设备验收和发布均需明确任务级授权。AWS 只使用 Lightsail，不创建 EC2。
- 密码、私钥、云凭据、面板 session、订阅 token、原始 URI、cookie 和秘密异常不得写进代码、参数、URL、localStorage、日志、截图、报告或 ledger。

## 变更和验证

开始时读取入口、约定、ledger、相关代码、Git 状态/差异、工具链和当前进度。Ledger 条目必须记录目标、路径范围、排除项、授权、假设、风险、时间规则和回退。保留所有用户脏文件和忽略运行数据。

行为代码按 TDD，先有能走真实代码路径的失败测试，再实现最小修复。上游未改动的基线验证依次做完整前端测试（unit/components/Storybook）、真实页面构建、`go mod verify`、`go test -shuffle=on -count=1 ./...`、`go vet ./...` 和包含真实页面的 Go build。上游默认 skip 的 PG、Xray gRPC、master/node 和 scale 用例要明确记为 skip。

当前 `scripts/check-local.sh` 和只读 `.github/workflows/ci.yml` 定义的源码门禁不包含实时面板、浏览器业务验收、真实 Xray 流量或发布。功能、数据库方言、节点同步、Xray 协议、部署和许可证改动时，再按具体风险增加门禁。构建和验收日志存本机私有目录并脱敏；项目只保存可审查的必要摘要。

每次收尾执行 `git diff --check`、基线/边界验证、秘密扫描和状态复核，记录精确退出码。门禁状态只能标为 `passed`、`failed`、`blocked`、`not-run`、`risky_not_executed`；依赖缺失或不能执行时保持未运行，不推导为通过。

## 历史与回退

当前切换没有创建本项目版本、commit、tag、GitHub Release 或生产部署。根 `VERSION=0.14.12`、旧 `CHANGELOG.md`、`docs/version-record.md`、旧验收矩阵和发布检查表保留作归档，不能作为新系统版本或能力声明。

应用源码回退指向旧提交 `ad90a0f4c5d58adab703ecfe25bf268321f5e44a`；本次具体文件以导入 manifest 为准。只回退本次相干文件，绝不 reset 整个共享工作树，也不恢复旧运行数据库、已撤销 Token、安全/云事件或凭据。

## 时间和复用

ledger 使用实际 aware ISO-8601 并显式换算 Asia/Shanghai 和 UTC；上游 GitHub 时间保留 UTC。当前项目只声明时区，不推断旧数据库时间语义。有效期边界在未来实现时要注明权威时钟、UTC 存储、TTL、半开/闭边界、DST 与重试，并测试边界前/恰好/之后。

可复用对象是固定来源归档、逐文件导入清单、npm/Go 锁文件和构建门禁。旧系统生产资源、PostgreSQL 数据、生产镜像和 Shadowrocket 失败/通过记录只具历史价值；不得把它们自动接到新底座。
