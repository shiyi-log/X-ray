# 独立 X-ray 管理平台设计规格

日期：2026-09-16。状态：用户逐项确认的设计之书面化版本；实现尚未开始。本文也是六个实施子计划的共同规格。文中的版本、测试目标和状态规则是新项目决策，不表示已完成部署或云端验证。

## 1. 目标与不可变边界

建设私有、自用的 X-ray 管理平台，统一管理 AWS Lightsail 与阿里云轻量应用服务器 SWAS，提供节点池、安装、检测、订阅与可验证的旧凭据撤销。

1. 一个全新 Git 单仓库，前后端放在一起，分别构建、运行，通过版本化 API 交互。
2. 前端使用 Vben Admin 二次开发；后端使用 Django 5.2、DRF、PostgreSQL、Redis、Celery。
3. 独立控制服务器、数据库、密钥、域名、备份和账号。管理面仅经 VPN、内网或 IP 白名单访问。
4. 仅一个超级管理员，无注册、邀请、普通用户、多租户或复杂 RBAC。云账号和设备访问身份均不是登录用户。
5. AWS Lightsail 和阿里云 SWAS 同时进入第一版；不实现 ECS。
6. 通用节点池，默认配额 3，可调；不能把三个槽位写死。
7. 四种订阅格式：Shadowrocket、Clash、Mihomo、V2Ray。保留撤销链接及让已导入旧节点凭据失效的强制撤销。
8. Shop、vue-shop-admin、shop-xray-installer 全部只读参考：不改、不删除、不复制历史迁移或运行数据，不导入其模块，不调用其部署资产。
9. 本机 `archive/` 是此前完整备份，禁止进入 Git、镜像、安装包、测试发现、文件监控、CI 上传及发布包。新数据库和凭据从零建立。
10. 第一版云资源变更由管理员显式发起。一次确认可以授权同一 Operation 的安装、重试、恢复和撤销失败隔离；周期性只读同步不允许隐式建机、换 IP 或删除。

## 2. 技术与仓库结构

选定基线：Python 3.13、Django 5.2 LTS、DRF 3.16、PostgreSQL 17、Redis 7.4、Celery 5.5；前端 Node.js 22 LTS（不低于 22.18）、pnpm 10.33.0、Vben Admin 5.7 系列、Vue 3、TypeScript、Ant Design Vue。P5.1 建仓时必须把 Vben 锁定到具体 tag 或 commit，并记录上游许可证和包清单；任何浮动的“5.7 系列”都不能进入 lockfile。安全补丁及全部传递依赖在实施时写入 lockfile；镜像使用固定摘要。安装器 Xray 版本必须先选定发行物并核实许可证和 SHA-256，不能在每次安装时拉取 latest。

```text
backend/
  config/                       设置、路由、WSGI/ASGI、Celery
  apps/identity/                超级管理员、TOTP、会话
  apps/cloud_accounts/          云凭据、厂商身份与能力
  apps/nodes/                   节点池、资源、端口和观测状态
  apps/operations/              操作状态、检查点、outbox、租约
  apps/subscriptions/           访问身份、凭据、修订、撤销
  apps/audit/                   追加审计
  common/                       加密、脱敏、错误、API 契约
  providers/                    base、AWS Lightsail、阿里云 SWAS
  tests/                        PostgreSQL 集成与适配器测试
frontend/                       Vben 应用和自有必要 workspace 包
installer/                      脚本、配置渲染、验证、版本清单
deploy/                         Compose、Nginx、镜像、备份、恢复
tests/                          安装器、跨服务、E2E、隔离边界
docs/                           规格、计划、运行手册、验收报告
archive/                        仅本机参考；绝不能打包
```

使用模块化单体。控制服务器 Debian 12 运行 Nginx、Django 管理进程、独立订阅读取进程、Celery Worker、PostgreSQL、Redis。订阅读取进程与 API 共用代码库，但使用单独 URLConf、数据库只读角色与最小订阅解密权限，不持有云账号、SSH 或 TOTP 解密密钥。

Vben 从许可清晰、固定提交的上游基线建立，保留许可声明；只保留必需 workspace 包。禁止引用同级 vue-shop-admin 的 node_modules、路径别名、API、登录或菜单。现有根目录空骨架保持不动，业务从 backend/ 和 frontend/ 开始。

## 3. 入口与信任边界

管理域名只提供前端和 `/api/v1/*`，同源会话，不放开跨域。生产不公开 Django admin、Swagger、调试或 metrics。

订阅域名只提供 `GET/HEAD /s/<opaque-token>?format=<format>`；其他路径拒绝。DNS 两个主机名可指向同一控制服务器，Nginx 分开虚拟主机、allowlist、限速和日志。默认虚拟主机拒绝未匹配 Host；后端不能信任客户端伪造的 Forwarded/X-Forwarded-For。

只有 443 公网开放；80 仅用于 HTTPS 跳转/证书验证。SSH 仅管理来源。PostgreSQL、Redis、API 进程都在内部网络。节点协议流量直接进入云节点，不通过控制服务器中转。

公开订阅日志不记录 URI、Token、查询参数或响应正文；记录路由模板、状态和匿名请求 ID。管理和 worker 日志统一脱敏。订阅内容以及所有 bearer token 都按秘密对待。

## 4. 领域模型与数据约束

| 模型 | 关键字段与约束 |
| --- | --- |
| SuperAdmin | 自定义 Django 用户从 0001 开始；singleton_key=1 唯一且数据库 CHECK；禁用并重建也不能产生第二个用户 |
| AdminSession | Django 服务端 session 的索引/元数据；授权只由 Django session 与 SuperAdmin.session_version 判定，索引不可独立授权 |
| CloudAccount | provider、当前 credential_version、经厂商验证的 external_account_id、启停与验证结果；有节点或未终结任务时不可硬删 |
| CloudCredentialVersion | 不可变的云凭据版本、加密材料、验证身份和创建时间；Operation 固定引用，旧版本保留到对账完成 |
| NodePool | UUID、名称、quota=3、allow_create；调整配额不能低于当前占用 |
| ManagedNode | 内部 UUID、pool/account/region/plan/image、外部 ID、地址、desired/observed/provisioning/health/security 状态、observed_at |
| NodeResource | 实例、静态 IP、防火墙规则等关联资源；外部 ID、归属标签、费用状态、是否可释放；不随节点记录删除级联销毁 |
| NodeProtocol | 一个可部署 endpoint：协议、监听地址/端口、TCP/UDP、传输、TLS/SNI/域名/证书引用、SS method、credential_scope、enabled |
| SshCredential / HostKeyRecord | 加密 SSH 凭据版本、候选与批准指纹、批准方式/时间；扫描结果不能自动信任 |
| NodeConfigRevision | desired/applied generation、配置 hash、Xray/安装器版本、bundle hash、部署及探测结果 |
| AccessProfile | 命名设备/用途身份，ACTIVE/REVOKING/REVOKED；无登录权 |
| NodeCredential | profile/node/protocol/version、加密材料、desired_generation/applied_generation、撤销时间 |
| Subscription | profile、当前 Token 指针、token_epoch、当前 revision、ACTIVE/REVOKED |
| SubscriptionToken | 历史 token 摘要、epoch、ACTIVE/REVOKED/EXPIRED、创建/撤销时间和 replaced_by；不保存原文，墓碑稳定返回 410 |
| SubscriptionRevision | 不可变序号、随机公开版本值、加密格式内容、节点/凭据版本引用、发布时间和 usable 标记 |
| PublicationBatch | 受节点故障影响的所有有效 profile 的排除节点修订；全部校验后一次事务切换指针 |
| Operation | UUID、kind/target、请求摘要、幂等键、状态、lease_owner/fence/expiry、费用与中断范围、检查点、错误 |
| OperationStep | 子目标、阶段、执行记录、外部 request_id、结果与验证证据；允许撤销按节点分别汇总 |
| OutboxEvent | 与 Operation 同事务创建，投递确认前可重复发布；消息只含 operation_id |
| AuditEvent | 追加动作、目标、操作者、结果、时间与请求关联；不保存秘密正文 |

实例唯一键为 `(provider, external_account_id, region, resource_id)`；云账号凭据轮换必须保持厂商实际账号身份不变。重复录入同一外部账号需拒绝或显式合并元数据，不创建第二套资源归属。

配额包含已预留且尚未确认释放的所有节点：创建中、运行、停止、安装失败、隔离、待删除、云端结果不明。删除确认后释放名额；失败且确认未创建云资源才能撤销预留。替代节点也占配额，额度不足时由管理员先调整额度，禁止偷偷溢出。

云厂商原始状态和错误码保留。状态观测失败写 observation_error 并保留上次观测时间，不能覆盖成 STOPPED 或 DELETED。资源 ID 在管理详情可完整显示用于确认，在普通日志/外部报告脱敏。

## 5. 单超级管理员与加密

`bootstrap_superadmin` 在服务器交互式创建唯一管理员，不把初始密码放进参数、镜像、永久配置文件或日志。数据库约束保证并发创建只能成功一次。

密码 Argon2id；密码验证后只创建短期 MFA challenge。首次登录只能进入 TOTP 绑定流程，完成一次验证码校验后才可进入控制台。TOTP 密钥加密、时间窗口严格限定、已使用时间步拒绝重放。恢复码高熵、一次显示、哈希保存、事务消费一次。

正式会话使用 Django 服务端会话与 `__Host-xray_session` Cookie（Secure、HttpOnly、SameSite=Strict、Path=/、无 Domain）；独立 cookie 和 CSRF 名称。管理 API 所有写请求（含登录）校验 CSRF，MFA 阶段不能调用管理资源。闲置 30 分钟、绝对 12 小时过期；危险动作要求最近 5 分钟内完成密码/TOTP step-up。

更改密码、重置 TOTP、本机恢复和“撤销全部会话”均提升 session_version。登录按账号和可信来源 IP 双限速；失败退避不导致永久锁死。服务器本机恢复命令写审计并作废旧会话，不能由远端 HTTP 调用。

秘密使用带 key_version 的 AEAD 信封加密；每条记录的实体 ID/字段名/版本作为 AAD 防止密文互换。至少拆分 control（云、SSH、TOTP）与 subscription（节点凭据、发布内容）密钥域。数据库只有包装后的 DEK 和密文。主密钥以 0600 文件只读挂载，独立版本；旧版本重加密完成并确认备份可恢复前不销毁。

普通管理 API 的云凭据只写不读；轮换验证失败保留原凭据。订阅/代理秘密只有独立、需近期认证的显式交付动作可返回。临时文件在 tmpfs 中以 0600 创建，任务终结清除；凭据不得出现在进程参数。

## 6. 可靠操作与并发模型

所有副作用入口校验 `Idempotency-Key: UUID`；作用域为唯一管理员、动作和目标，保存 canonical request hash。同键同参数返回原 Operation；同键异参数返回 409 `IDEMPOTENCY_CONFLICT`。成功受理返回 202、Location 与 operation_id，不等待远端完成。

合法状态转换：

```text
PENDING → RUNNING → SUCCEEDED | FAILED | PARTIALLY_SUCCEEDED | NEEDS_RECONCILIATION
RUNNING → RETRY_PENDING → RUNNING
PENDING → CANCELLED
RUNNING → CANCELLING → CANCELLED | NEEDS_RECONCILIATION
PARTIALLY_SUCCEEDED → RETRY_PENDING（仅重试未完成的子步骤）
NEEDS_RECONCILIATION → RUNNING（先取证再决定续跑）| FAILED | SUCCEEDED
```

SUCCEEDED/FAILED/CANCELLED 终态不再被旧 worker 改写。取消是检查点协作取消，不能撤回已成功的云操作；存在资源必须在结果中保留。强制撤销一旦令牌失效，不允许取消后重新启用旧凭据。

事务内锁节点池、预留名额、创建 Operation 和 OutboxEvent；事务提交后投递 Celery。outbox 重投保证数据库已提交但 Redis 失败时不丢任务。worker 使用 PostgreSQL 租约与递增 fencing token，并在每个外部步骤前后核对有效所有权；Redis 锁仅作辅助。远端配置使用 generation CAS 和原子文件锁拒绝旧任务覆盖新撤销配置。

云 API 不接受 fencing token 时，租约过期绝不能立即由新 worker 重放不确定写入；先进入 NEEDS_RECONCILIATION，查外部 request_id、确定名称、标签、账号与区域。不确定创建结果维持预留，不能重复收费。

自动重试只覆盖网络/限流等已知可恢复情况，指数退避、有总上限；权限、余额、参数错误不盲重试。DB 不持长事务等待云或 SSH。未知外部结果与本地失败分别报告。

## 7. 双云接口与能力真实性

`CloudProvider` 核心方法：validate_credentials、list_regions、list_plans、list_images、create_instance、find_instance_by_request、get_instance、start_instance、stop_instance、reboot_instance、delete_instance、get_public_ip、rotate_public_ip、configure_firewall、get_capabilities。所有写方法接收 operation key，返回外部结果和原始状态。

能力需要区分 `SUPPORTED / UNSUPPORTED / UNVERIFIED`，并说明区域/套餐限制及证据日期。第一版两个适配器都要可创建、查询、启停、重启、归属确认、网络隔离、删除；具体产品是否允许退款/释放、重装和原地换 IP 必须查官方 SDK/文档并写契约，不能用空实现假装支持。

AWS 静态 IP 流程与阿里云分配地址语义不能混用。阿里云原地换 IP 默认关闭，未经能力证据不得开启；提供“创建替代节点”流程。方案报价显示币种、周期、采集时间、税/流量等未包含项；不能把停机显示为停止计费。

防火墙由本系统独占管理节点协议端口。纳管、安装、开放和撤销前必须读取全量规则；发现无法证明归属的同端口或全端口 IPv4/IPv6 allow 时，正常发布和隔离判定都阻断。经危险确认后可以临时替换受管协议端口的完整规则集，只保留管理 SSH，并保存精确快照；恢复时按当前期望状态重算最小规则，不盲目回放旧快照。Provider 分成读取、计划、应用和有效暴露验证四步；规则应用成功不等于公网断流，必须同时有规则回读及 IPv4/IPv6、TCP/UDP 数据面证据。控制服务器身份永远不能被纳管为 ManagedNode。

## 8. 节点流程与安装器

创建：报价/影响预览 → 确认 → 配额预留 → 确定资源命名和幂等标识 → 云端创建 → 保存 ID → 等待运行 → 地址与防火墙配置 → PROVISIONED。云创建成功、后续安装失败保留资源并显示持续费用。

安装：PROVISIONED → SSH 验证 → 上传固定版本包 → SHA-256 → 生成候选配置 → `xray run -test` → 原子替换 → systemd 重启 → 本机服务/端口检查 → 目标节点代理探测 → READY。

SSH 首次指纹来源为厂商可信启动信息或管理员独立核验；初次自动扫描得到的指纹只算候选，不能直接 auto-add。已固定指纹发生改变中止任务。安装器所有动作限定结构化参数，拒绝任意 shell 命令；bundle 中保留许可证、固定版本和校验和，不包含运行凭据。

协议第一版覆盖 Shadowsocks、SOCKS5、VMess、VLESS、Trojan。裸 VLESS/VMess、SOCKS5 的风险通过明确的传输能力配置说明；支持 TLS 的协议默认校验证书，生产不得依赖 allowInsecure。Trojan 等 TLS 节点需域名/受信证书或可验证 pin；未满足时禁止把协议标为生产 READY。

协议撤销能力必须通过固定 Xray 版本逐个验证。能多用户的协议分配 profile 独立凭据；共享密钥协议轮换整个协议的密钥并告知所有受影响 profile。不能假设 Shadowsocks 的任意密码格式/加密算法均支持多用户。

普通安装失败可恢复上个有效配置；安全撤销失败禁止恢复含已撤销身份的配置，必须隔离。远端 generation 单调增长，保留有限份 root-only 加密或受保护备份；备份不参与自动回滚到已撤销版本。

检测：云态、本机配置与服务、公网协议可用性、通过节点 SOCKS5 的 socks5h 请求 Google generate_204。清空本地 proxy 环境与 curlrc，凭据走 stdin。Google 失败标为探测目标失败，不能等同于所有协议不可用；普通检测只更新健康，不自动换 IP。

换 IP：暂停发布 → 提交支持的云操作 → 保存并核验新地址 → 更新防火墙/证书与配置 → 探测 → 发布新修订。更换前确认旧连接中断及费用，历史 IP 不自动释放。

替代：预留第二个名额 → 新建并验证 → 切换订阅 → 旧节点 RETIRING。旧实例需另行停止或删除确认；旧凭据的失效遵守撤销协议，不以订阅消失替代。

删除、静态 IP 释放为两个独立动作，无批量删除；执行时重读归属和资源状态。重装清除磁盘数据，必须单独告知和确认。代理启停可恢复并不代表无成本或无中断。

## 9. 订阅、版本与强制撤销

AccessProfile 是设备/用途身份。每个 profile 只发布已 READY、未隔离、凭据版本已应用的节点；快照含各格式实际兼容的协议，Clash 不支持的协议不得伪造，空交集给明确错误。发布验证使用真实解析器/客户端兼容性 fixture。

原始订阅 Token 使用至少 256 bit 随机数，仅创建/轮换时返回一次；数据库保存 SHA-256 digest 与 tombstone，不存可恢复原文。前端在当前受控交付窗口缓存 URL 以复制；刷新后需要轮换获取新 URL，旧 Token 随即返回 410。修订更新不必轮换 Token，已有客户端可继续获取最新修订；随机 v 是缓存版本，不是授权凭据。

四格式同一次发布生成同一不可变修订。公开接口每次查询 Token 与 profile 撤销状态，限制读当前 usable revision；`v` 不能取回旧修订。DB 不可用返回 503，不使用绕过撤销的陈旧缓存。第一版所有订阅响应 `Cache-Control: no-store`，禁止 CDN/代理缓存；不承诺能删除客户端已保存内容。

仅停用链接：Token 原子标记撤销，后续 GET/HEAD 返回 410；未存在 Token 404，正文长度一致、限速。这一操作不保证节点访问失效，UI 明示。

强制撤销采用 fail-closed 的节点顺序：同事务撤销 profile/Token、冻结相关发布并创建 Operation；节点进入 REVOKING 后保留 SSH 管理通道，先关闭受管协议端口或停止 Xray，确认不能新建旧连接，再部署不含撤销身份的新 generation，校验配置并启动服务但保持协议端口关闭，最后按最小规则重新开放并验证旧凭据新连接失败、旧持续会话已断开、未撤销 profile 的新一代凭据成功以及 applied generation/hash 一致。唯一 profile 被撤销时可创建临时探测凭据作为正向控制，验证后销毁。传播窗口内界面显示 REVOKING，不把 202 当成已全部失效。

每个节点保存撤销状态：REQUESTED → APPLYING → CONFIG_APPLIED → SERVICE_RESTARTED → VERIFIED_REVOKED。不能只因旧凭据超时认定成功，必须有正向网络控制或服务端认证证据。

失败立即使该节点所有引用的修订不可用，并以 PublicationBatch 为所有其他有效 profile 生成排除它的新修订；新修订未就绪时只有这些仍有效 profile 返回 503，被撤销 Token 始终返回 410。执行管理员在强制撤销确认中已经同意的安全隔离：关闭云防火墙协议端口、回读规则并验证 IPv4/IPv6、TCP/UDP 与既有连接。隔离完成为 QUARANTINED，表示该节点整体不可达，不能冒称某身份已完成精确移除。

如果 SSH、云 API 或数据面证据不足，标记 REVOCATION_UNCONFIRMED / ISOLATION_UNCONFIRMED，Operation 为 PARTIALLY_SUCCEEDED 或 NEEDS_RECONCILIATION，控制台显示红色持续风险；不能保证离线节点上的旧凭据已经失效。没有自动删除、释放 IP 或绕过未知状态。

整体节点凭据轮换生成所有有效 profile 的新版本，撤销旧版本与旧连接；共享 endpoint 的旧凭据会让其他 profile 的已导入旧配置一起失效，验收承诺只针对其他 profile 的新一代配置，Action Preview 必须列出全部受影响身份和刷新要求。恢复隔离必须人工操作，先清除所有历史撤销身份、验证新配置，再按最小规则开放并重复正反向探测；不能先对全网开放再验证。

## 10. API 与前端交互

管理端点：auth、cloud-accounts、node-pools、nodes、operations、access-profiles、subscriptions、audit-events、system，统一 `/api/v1/`。OpenAPI 生成前端类型，生成结果可重现且 CI 检查差异。仅列出资源 ID/脱敏状态，秘密通过显式交付接口。

异步响应 `{"operation_id":"uuid","status":"PENDING","target_type":"node","target_id":"uuid"}`；统一错误 `{"code":"NODE_OPERATION_CONFLICT","message":"该节点已有进行中的配置操作","retryable":false,"operation_id":null,"details":{}}`。

危险动作先取得短期 ActionPreview，包含目标、external ID、资源/凭据 generation、价格时间戳、影响范围与确认文本。提交带 preview_id、确认文本和幂等键；服务器重验预览绑定、step-up、归属和新鲜度，防止复制确认文本对新资源误操作。

Vben 页面：密码/TOTP/恢复码登录；总览、云账号、节点池、节点、操作中心、访问配置、订阅管理、审计日志、系统设置。没有用户/角色列表。系统设置只读展示管理 allowlist、域名、TLS、CSRF 和版本信息；这些值由服务器部署配置修改，Django 不写 Nginx、DNS、证书或主机防火墙，不能把管理员静默锁在外面。

操作中心从后端恢复进度，首版轮询，可取消动作以 Operation.can_cancel 为准。空状态为真实空数据；API 失败明确展示失败，不返回演示节点或随机指标。编辑字段保存失败回滚 UI；秘密在 dialog 关闭、超时、退出登录后清除。强制撤销单独展示“链接已撤销”和“节点访问已验证失效”的进度。

## 11. 部署、发布、备份与灾难恢复

Compose 包含 nginx、admin-api、subscription-api、worker、outbox-dispatcher、postgres、redis、backup，前端在构建阶段生成静态文件。只读周期任务可由 scheduler 执行；没有默认启用的云写定时任务。

镜像构建使用明确目录 allowlist；`.dockerignore` 必须排除 archive、.git、.env、所有密钥/数据库/日志/备份。生产 secrets 位于 `/etc/xray-manager/secrets/`，目录 0700、文件 0600，按容器分配；bootstrap 密码交互输入，不留长期 initial-admin 文件。

发布：备份 → 验证镜像摘要 → migrate --plan 和兼容性检查 → migrate → migrate --check 必须通过 → 停止旧 worker 领取并等待安全检查点 → 新进程健康检查 → 切换入口。迁移前 `migrate --check` 可用于记录待迁移状态，不能把非零待迁移结果当作永久阻断。

数据库兼容当前与上一版本应用，破坏性变更分版本完成。回滚应用不撤销云操作，也不恢复历史 revoked 凭据。worker 消息带 schema_version，未知版本停止处理并告警。

备份：每日及发布前 PostgreSQL 加密备份，7 日+4 周保留；至少一份加密离机副本。备份数据库、部署和迁移版本、安装器摘要、审计与撤销记录。control/subscription 包装主密钥及备份解密密钥分别做受保护的离机托管，否则数据库备份无法恢复；日常数据库备份不包含这些明文钥匙。

Redis 不是事实来源，恢复后重建 outbox/任务调度。每月隔离恢复演练，演练环境禁网，不执行云操作。恢复后默认 MAINTENANCE：管理只允许恢复流程，订阅 503，worker 不执行云写。对照独立追加的撤销审计副本完成安全记录追平并核验云资源及任务；若不能证明撤销状态最新，保持订阅关闭并对新系统管理的全部 Token/节点凭据重新撤销或轮换，直到验证完成。

日备份的目标 RPO ≤24h、目标 RTO ≤4h 需演练测量；安全撤销状态不允许因恢复而重新启用，离机安全事件增量备份与恢复关闭策略共同保证。日志/审计保留：普通脱敏日志 30 日、操作及安全审计至少 365 日，管理员可延长。

## 12. 测试和完成门禁

本地/CI：单元、真实 PostgreSQL 并发和迁移、Redis/Celery/outbox 故障、双云 SDK Stub、安装器 dry-run/ShellCheck/本地 Xray 校验、四格式解析、撤销正反向/部分失败/旧 worker、OpenAPI、Vben 单测/typecheck/lint/build、Playwright、Compose 校验、镜像边界和秘密扫描。

能力证据必须区分：文档已核对、SDK stub 通过、沙箱容器已验证、真实云已验证。真实双云创建/费用/SSH/Google/隔离/删除，需要用户再授权具体测试账号、区域、套餐、预算；删除与 IP 释放单独授权，不能因为“完成测试”自动执行。

代码完成：六阶段所有本地门禁通过；Shop 零依赖；唯一管理员、双云、配额/幂等、安装器、四订阅、撤销异常诚实呈现、完整 Vben 和隔离部署均实现。运行验收：在两个授权平台及独立控制服务器通过真机矩阵，记录费用与残留资源。二者分开签字，Mock 通过不等于生产可用。

## 13. 六阶段与范围追踪

| 阶段 | 交付 | 主要规格章节 |
| --- | --- | --- |
| P1 | 仓库/隔离环境、单管理员、密钥与 API 基础 | 1–5、10 |
| P2 | 云账号、双云契约和能力矩阵 | 4、7 |
| P3 | 节点池、可靠 Operation、安装器和云流程 | 4、6–8 |
| P4 | 访问身份、订阅、可验证强制撤销/恢复 | 5、6、9 |
| P5 | Vben 二开、类型契约和管理交互 | 3、5、10 |
| P6 | 独立部署、密钥恢复、全链路与真机门禁 | 11–12 |

执行时再填写的环境值包括独立服务器地址、域名、管理网段、离机备份位置、双云测试账号/区域/预算、Git 远端。这些值不妨碍本地实现；不得从 Shop 配置中补齐。

## 14. 只读参考证据

2026-09-16 核对：Shop HEAD `fe53b700d9de4f73a1c37e7ebe730c46100b7d32`，Vue Shop Admin HEAD `0d8ba69`，安装器 HEAD `4ed7969`。源 Shop 后续出现 `cloud/xray_install.py` 与 `cloud/tests_xray_install.py` 外部未提交改动，本任务未修改它们。

借鉴点仅是：人工触发、Google socks5h 检测、订阅格式与操作文案、节点操作串行化经验。固定三槽位、Shop 鉴权、订单/生命周期、共享配置、既有密钥和历史迁移不继承。新项目测试期望由本规格定义。
