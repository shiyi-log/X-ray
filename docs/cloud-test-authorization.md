# 真实云验收授权单

本文件定义一次真实 AWS Lightsail 或阿里云 SWAS 验收所需的最小授权。空白模板
不是授权；聊天中的泛化“测试一下”也不包含删除实例或释放 IP 的权限。

## 授权记录

每个平台单独填写并关联不可变审批编号：

| 字段 | 必填内容 |
|---|---|
| authorization_ref | 审批/工单/消息的不可变引用 |
| provider | `aws-lightsail` 或 `aliyun-swas` |
| account_ref | 脱敏账号引用，不记录 access key |
| region | 唯一区域 |
| plan_id / image_id | 允许的固定套餐和镜像 |
| budget | 币种、总额、预警值和计费负责人 |
| max_lifetime | 实例/IP 最长存活时间和截止时间 |
| allowed_actions | create/read/firewall/install/probe/quarantine 等逐项列出 |
| stop_authorized | 是否允许停机及确认人 |
| delete_authorized | 是否允许删除实例及独立确认人 |
| release_ip_authorized | 是否允许释放静态 IP 及独立确认人 |
| ssh_scope | 目标、用户、指纹来源和允许命令边界 |
| public_probe_scope | 允许的目标、协议和时间窗口 |

预算超限时停止创建新资源并报告，不自动删除已有实例或释放 IP。授权到期、账号
归属不符、区域/套餐/镜像不符、SSH 指纹不符或 provider 结果未知时立即停止后续
写入并进入对账/隔离流程。

## 执行证据

每个写操作必须记录完整 Operation UUID、provider request ID、带时区时间、区域、
脱敏资源引用、read-after-write 结果和成本变化。五协议与撤销探测分别记录：

- 操作前接受预期、操作后拒绝预期；
- 使用的 credential reference，不保存凭据正文；
- socks5h/目标/超时和原始成功或失败分类；
- 防火墙/SSH/云结果不确定时的 quarantine 证据；
- 重试是否复用同一幂等键以及最终对账结论。

## 收尾与残留

停机、删除实例、释放 IP 是三个独立动作，只执行本次授权为真的动作。结束时填写
费用、实例/IP/快照/防火墙等残留资源清单、下一责任人和最晚处理时间。未获授权的
危险动作在矩阵中记为 `risky_not_executed`，不得用“测试完成”隐去残留。

## 当前状态

当前没有任何已填写且有效的授权记录，因此 AWS/SWAS 真实写入、远程 SSH、Google
公网探测、实例删除和 IP 释放均未执行。


## 2026-11-08T02:50:16+08:00 — 自托管 runner 本机 AWS CLI 授权落地

本记录适用于本次 CI 基础设施创建，与上面的历史“当前状态”分别按时间解释。用户已明确要求创建自托管 runner，并指定使用本机 AWS CLI；配置由代理选择，延续测试资源 USD1,000 总预算。此记录不授予修改已有应用节点或绕过应用 MFA 的权限。

| 字段 | 本次精确范围 |
| --- | --- |
| authorization_ref | 本线程“创建自托管runner”“目标2h4g”“使用本机 aws cli 创建”及原始 USD1,000 测试预算授权；run `xray-self-hosted-runner-20261108-01` |
| provider / account_ref | aws-lightsail / account SHA256 `4a0ef08458dd`，本机 root profile；不复制凭据 |
| region / zone | ap-southeast-1 / API 确认可用后选择单一 zone |
| plan / image / instance | medium_3_0 / ubuntu_24_04 / xray-actions-2x4-20261108-01 |
| budget | API USD24/月，2 vCPU/4 GiB/80GB/IPv4；本次只创建一台，目标一个月约 USD24，流量等按提供方计费；总授权上限 USD1,000，不创建静态 IP 或快照 |
| max_lifetime | 初始计划 30 日，截止 2026-12-08T03:00:00+08:00；需在截止前复核保留/清理；不能把停止虚拟机误认为停止 Lightsail 套餐计费 |
| allowed_actions | 在上述唯一新建目标上 create/read/tag/firewall/update-instance-metadata-options/SSH 安装及系统服务配置；GitHub 此仓库 runner 注册、状态读回和 trusted workflow 配置 |
| stop_authorized | 仅此新建 CI 目标在故障隔离/任务回退时停机；不停止已有主机 |
| delete_authorized | 没有用户对已有实例的删除授权；不删除已有资源。本次新建失败资源的清理按任务范围处理，记录精确目标；任何不明确的删除保留并报告 |
| release_ip_authorized | 不申请、不释放静态 IP |
| ssh_scope | 仅上述新建实例；GetInstanceAccessDetails 通过 AWS 官方控制平面获取短时访问凭据和 host keys，全部只在控制器内存使用；用户名为服务端返回值；SSH/入站只允许当前操作出口 /32，安装完成关闭全部公网入站 |
| public_probe_scope | AWS 官方出口地址查询、GitHub API/runner release/Actions、Ubuntu apt/Docker registry/锁定依赖源；只用于 runner 安装、状态和 CI 验证，无应用数据平面探测 |

runner 使用专用低权限用户运行，Docker 权限限于这台专用 VM；用户 PAT、AWS credentials、SSH 控制私钥和短时注册 token 不落远端磁盘。runner 运行必需的自身机器身份按官方机制保存在专用目录且限制权限。GitHub 查询已确认只有一名 admin 协作者、私有 fork PR workflows 关闭、默认 workflow token 只读。persistent runner 只路由受信任 main/tag，不把 label 表述成 GitHub 服务端隔离机制。

执行回读（2026-11-08）：Lightsail 实例已创建并保持 running，套餐 medium_3_0，IMDS endpoint 关闭且 token required。GetInstanceAccessDetails 的 SSH hostKeys 为空；短暂开放到本机出口 /32 的 TCP/22 仍未获得可信 host key，随后已关闭并读回无公网入站。未 SSH、未创建 GitHub 注册 token、未安装或注册 runner；GitHub API 读回 runner 总数为 0。实例当前仍运行，套餐标价约 USD24/月，实际累计账单未读回；expires-at 标签不执行自动停机或删除。此次授权明确涵盖创建与配置，但未明确授权删除新实例，因此保留目标，不执行 DeleteInstance。

授权边界更正：前述计划表中“新建失败资源可按任务范围清理”的文字不替代用户对 AWS 删除动作的明确授权。后续如需删除本次实例，必须另行取得针对精确实例的任务级授权。

## 2026-11-08T03:52:23+08:00 — EC2 / SSM runner fallback

因前述 Lightsail API 未返回可 pin 的 SSH host key，改用本机 AWS CLI 评估并配置一台独立的 EC2 runner 管理通道。授权来源仍为本线程明确的“创建自托管 runner”“目标 2h4g”“使用本机 aws cli 创建”及测试资源 USD1,000 上限。本次不复用其他项目已存在的 EC2 实例、IAM profile、security group 或 runner。

| 字段 | 本次精确范围 |
| --- | --- |
| run_id | `xray-self-hosted-runner-20261108-01` |
| provider / account_ref | 本机 AWS CLI `AWS_PROFILE=root`；account fingerprint `4a0ef08458dd` |
| region / instance | `ap-southeast-1` / 单台 `t3.medium`，Ubuntu 24.04 x86_64，2 vCPU / 4 GiB，名称 `xray-actions-ec2-2x4-20261108-01` |
| network | 专用 security group，零入站规则；公有子网只用于出站访问 GitHub、依赖源和 SSM；不创建 key pair，不开 SSH |
| administration | 专用 EC2 instance role/profile，只附加 AWS 托管 `AmazonSSMManagedInstanceCore`；用 Session Manager 建立管理会话，注册 runner 时不把 token 写入 user-data、命令日志或本地文件 |
| budget / review | AWS Price List 当前 `t3.medium` Linux Singapore 价 USD0.0528/小时，按 730 小时约 USD38.54/月；EBS、IPv4 和网络另计。连同仍运行的 Lightsail runner 计划费约 USD24/月，目标成本约 USD70/月，远低于 USD1,000 上限。计划于 `2026-12-08T04:00:00+08:00` 复核资源；标签不自动停机或删除，实际账单须另行读回 |
| allowed_actions | 创建并标记此专用实例、security group、IAM role/profile；安装 SSM Session Manager 本机插件到用户级目录；通过 SSM 安装/配置专用 runner 用户、Docker、Playwright 浏览器系统依赖与本仓库单 runner；只让受信任 main CI 和从 main 手动触发的发布使用该 runner |
| exclusions | 不 SSH、不创建 SSH key、不配置公网入站；不触碰已有 EC2/runner/IAM profile；不注册 PR workflow；不将 runner token、PAT、AWS credentials 或私钥写入仓库、user-data、SSM 命令参数、日志或本地文件；不删除 Lightsail 或 EC2 实例，不释放 IP |

实际资源创建前置：当前 EC2 API 只读确认 `t3.medium` 为 2 vCPU / 4 GiB；Ubuntu 24.04 Singapore AMI 已读回；默认 VPC 有可用公有子网；SSM 可见另一台已有 Ubuntu managed node。当前 AWS Price List 读回为 USD0.0528/小时。以上不是本次 EC2 创建成功证据；任何尚未创建或未读回项目继续标为 `not-run`。

执行结果更正（2026-11-08）：因 Lightsail host key 仍为空，使用上述授权创建 EC2 `i-092e2bb13b7821d13`、独立 IAM role/profile `XrayActionsRunnerSsm20261108` 与零入站 security group `sg-05b46b434a9bbbabc`。实例为 `t3.medium` / Ubuntu 24.04 x86_64，50GB 加密 gp3，IMDS token required；SSM manager `Online`，实例与系统健康检查均 `ok`。没有创建 key pair 或 SSH 入站。GitHub runner 2.338.2 的 Release API SHA-256 校验通过，runner service 为 `active (running)`；GitHub API HTTP 200 读回 runner `online`，labels 为 `self-hosted, Linux, X64, xray-trusted-2x4`。注册 token 只在内存和受保护 SSM 会话中短暂使用，没有写入仓库、user-data、SSM command、日志或本地文件；远端 `.credentials` 与 `.credentials_rsaparams` 均为权限 `600`。当前没有活动 SSM 会话。

更正工作流信任范围：Release tag push trigger 已移除；发布只能由 main 上的 `workflow_dispatch` 启动。工作流先从 main 校验输入标签格式、annotated 类型、标签内版本和目标提交可达 `origin/main`，通过后才检出发布提交。此 workflow/test 修正已经本地通过 focused tests，但尚未提交或推送，因此远端 CI/Release 仍是 `not-run`。新增 EC2 与旧 Lightsail 目标都仍运行；预算估算合计约 USD70/月（不含实际账单读回），`ExpiresAt` 标签不自动关停/删除。未触碰 X-ray 应用节点或订阅，真实应用侧生命周期验收仍未运行；后续仅使用专用本地数据库与 Fake/Stub 完成本地门禁，真实 CloudAccount 前置未达成前不执行应用侧 AWS 写入。

Release 工具补齐（2026-11-08）：SSM 只读预检确认 runner 原先未安装 `gh`，Ubuntu `noble-updates/universe` 提供 `2.45.0-1ubuntu0.3`。通过 AWS CLI SSM RunCommand `d8c8e005-af41-42a5-bacb-addad4a0c285` 安装 Ubuntu 仓库的 `gh 2.45.0`；命令退出码 0，`gh release create --help` 可用。没有写 GitHub token、修改 Actions secrets 或打开主机入站；安装仅作用于 EC2 `i-092e2bb13b7821d13`。`gh` 已具备不代表 Release 已执行；仍需推送受信任 main 后回读 CI，再手动 dispatch 并验证 tag/Release/资产。

首轮远端 CI 纠正（2026-11-08）：Actions run `42414036396` 的 job `128528139687` 确认运行在 runner `xray-actions-ec2-2x4-20261108-01`，setup steps 成功，但锁定依赖步骤因 `playwright install --with-deps chrome` 需要 sudo 而失败；专用 `actions` 用户没有 sudo，artifact 缺失又造成次级错误。基于锁定 Playwright 1.55.1 的 Ubuntu 24.04 `nativeDeps.js` 清单，通过 SSM 在 EC2 安装浏览器运行库/字体。首条安装命令包安装成功，但尾部核验因 shell 参数转义错误返回 2；后续 `dpkg-query` 读回命令 `3fbee0eb-71d2-43c0-bbbd-ca3f91113bf5` 返回 0，确认依赖包齐全。CI workflow 已改为只下载 Chrome，不在 Actions 作业内安装系统包；artifact 缺失改成 warning，减少前置失败时的次级噪声。修正版仍需推送和远端重跑验证。

根因更正（2026-11-08）：后续 run `42415064430` / job `128531250854` 证明即使移除 `--with-deps`，`playwright install chrome` 仍会通过 Playwright 1.55.1 的 `transformCommandsForRoot()` 调用系统级 Chrome 安装脚本，触发 sudo；已安装 Linux 浏览器依赖并不能避免这一步。按锁定源码和失败日志，将 CI 改为下载 Playwright 管理的 `chromium`，并移除主 E2E 配置中的 `channel: 'chrome'`。本地执行 Chromium 安装及主 E2E 通过（8 项），远端新 CI 尚待推送验证。浏览器 E2E 运行使用已登记空闲端口 9537、9538、9541、9542；独立 `xray-cloud-acceptance` 服务未停止、未复用；临时认证状态、截图和报告目录已删除。

runner CI 验证继续（2026-11-08）：推送 `dc06d8d65bb9dd853fdad1b550ad295edab12a43` 后，run `42421788707` / job `128551579276` 已成功执行依赖安装、验收预检、Compose 配置、Django、迁移漂移、Ruff 和 backend/frontend/backup-tools 镜像构建，随后在 `backend-tests` 的固定 Xray 测试二进制下载步骤因 runner 未安装 `unzip` 失败。artifact `13593881867`，摘要 `sha256:6e463fdcf16ace4cf9a330e142c11eb6647f7ac1b13fdf02d08f1a046c7ed372`；上传和 runner 资源清理步骤均成功。代码候选改用 Python `zipfile` 只提取已通过 manifest SHA-256 校验归档内名为 `xray` 的固定成员，不依赖系统 unzip。临时 ZIP 的存在/缺失成员回归 3 项通过；完整本地 19/19 gates 通过，backend/delivery `488 passed, 2 skipped`，前端 84、E2E 8 均通过。首次本地 E2E 因独立当前主线服务占用 `55433/56380` 退出 1；保持其运行，改用已登记 `55671–55674` E2E 端口与 `55435/56382` 门禁数据库端口后全量通过。测试 Compose 容器/network 已移除且保留本轮命名卷，所选端口复核为空闲。

本轮 AWS CLI 仅做身份/权限只读诊断：default profile 的账号指纹为 `sha256:b1746f68f5be`，其 EC2/SSM describe 请求被拒绝；root profile 的账号指纹为 `sha256:4a0ef08458dd`，与 runner 授权记录一致。通过 root profile 只读查询专用 runner `i-092e2bb13b7821d13`，状态为 `running`。本次 CI 提取修复没有触发 AWS 写入。该身份读回不证明 X-ray 应用 CloudAccount/MFA 已配置，也不改变真实应用节点、动态 IP/健康、订阅创建/撤回或流量验收仍 `blocked`/`not-run` 的状态。

## 2026-11-09T21:28:38+08:00 — 节点池、动态 IP、订阅与计量验收

用户本轮明确要求在 AWS 创建测试服务器，配置由代理选择，测试节点数量补齐/缩容、每日一台 stop/start、动态 IPv4 与状态/健康同步、订阅创建/撤回、节点数量核对和流量统计，并授权费用不高于 USD 1,000。此记录把执行范围进一步限缩为一台 Lightsail 测试节点；所有节点写入都必须通过 X-ray 正常 CloudAccount/Operation、近期 step-up、预览、幂等和审计路径。测试资源不会与现有 runner 或其他 AWS 资源混用。

| 字段 | 本次精确范围 |
| --- | --- |
| authorization_ref / run_id | 当前对话 2026-11-09 用户请求；`xray-node-pool-restart-20261109-01` |
| provider / account_ref | AWS Lightsail / 当前只读 AWS `root` profile caller account SHA-256 `94a91b85428b`；凭据不复制或输出 |
| region / plan / image | `us-east-1` / `small_3_0` / `ubuntu_24_04`；用户授权代理选择配置；目录读取 USD 12/月，实际费用以账单为准 |
| resource identity | 仅本 run 通过 X-ray `node.create` 创建并读回的单个节点；通过 run ID 和 Operation/ManagedNode UUID 追踪，禁止复用或删除既有实例 |
| task budget / lifetime | 用户总上限 USD 1,000；本测试子预算 USD 5；最多一台、最长两小时，最迟 `2026-11-09T23:30:00+08:00` 经 X-ray `node.delete` 删除并读回；不创建静态 IP、快照或额外实例 |
| allowed_actions | 仅该测试节点的 create/read/tag、应用所需 firewall 配置、自动 bootstrap、节点状态/IP/健康读回、计划 stop/start、通过该节点自测订阅和流量、以及把该节点池额度设为 0 后由 pool scheduler 提交 `node.delete` 并完成云端读回。每一云写入均用新的 UUID `Idempotency-Key` 并保留 Operation/审计证据 |
| ssh_scope | 仅该测试节点；使用 Lightsail `GetInstanceAccessDetails` 提供的临时认证信息和 AWS 返回的 host key pin；只走应用 `NodeBootstrapRuntime`，不使用 `ssh-keyscan`/TOFU、不访问其他主机，密钥只在进程内存 |
| public_probe_scope | 只连接本轮测试节点的 IPv4 和本轮短暂开放的服务端口；客户端来源限制到当前运行主机的单一出口 `/32`。出口地址仅向 AWS 官方 `checkip.amazonaws.com` 做一次只读查询并只在内存使用。流量统计目标使用测试节点 loopback echo，不请求第三方网站 |
| stop / delete / IP release | `stop_authorized=yes`，仅由每日重启验收对本轮节点执行；`delete_authorized=yes`，仅缩容验收删除本轮节点；`release_ip_authorized=no`，不创建/释放静态 IP |
| exclusions | 不触碰现有 Lightsail/EC2 runner、其他 AWS 账号/区域/资源；不做公开第三方探测、生产 TLS/生产域名、设备验收；不输出凭据、订阅 Token/原始 URI、私钥、Cookie 或完整公网地址 |

AWS CLI 只读预检（2026-11-09 21:28+08）：`sts get-caller-identity` 仅保存 SHA-256 摘要；`us-east-1` Lightsail 当前实例数为 0、无 run-name 冲突；`small_3_0` 目录读取价格为 USD 12/月、2 vCPU；未执行创建、SSH 或其他云写入。若应用不能在上述范围内安全完成运行时初始化、来源限缩或费用读回，应停止后续写入并保留失败/阻塞证据。

### 2026-11-09/10 — 授权节点执行与清理收据

- 使用正常 X-ray CloudAccount、step-up、Operation、UUID 幂等、outbox/Celery、审计和读后写路径，仅创建 1 台授权节点；创建 Operation `d3b10617-d1eb-4eb7-a99e-f6e82c055f9a` 于 2026-11-09T22:23:45+08:00 建立，`cloud.create` 步骤于 22:44:03+08:00 返回接受。
- stop/start、动态 IPv4 更新、健康探测、refresh、UsageCheckpoint、订阅签发/公开读取/撤回均按项目台账 `xray-node-pool-restart-20261109-01/006` 读回；不在本文件保存 Token、URI 或公网地址。
- profile 级撤回 Operation `40f464a8-18db-464e-be5d-00b71b075831` 为 `PARTIALLY_SUCCEEDED/REVOCATION_UNCONFIRMED`；池调度器 fail-closed 阻断自动删除。随后仅对本授权节点执行标准 `node.delete` Operation `785ed5d2-693d-4f13-b545-16eb5f9dd916`；provider `CONFIRMED_ABSENT` 读回于 2026-11-09T23:13:17.716837+08:00，早于 23:30 截止。节点计数为 quota 0 / used 0，无静态 IP 或快照残留。
- 2026-11-10T00:00:58+08:00 的 Cost Explorer 只读查询对 2026-11-09 的账号级 Amazon Lightsail 服务汇总返回 USD 0.00。该值不具备实例级归因且可能受计费延迟影响，不能据此宣称本节点实际成本为 USD 0；实际最终账单金额仍待 AWS 账单结算。AWS 说明 Lightsail 实例按小时计费并受月费上限约束，删除后停止实例费用；本次确认没有静态 IP、快照、磁盘或负载均衡器残留。

## 2026-11-10T00:31:00+08:00 — 双节点真实池自动缩容补验

用户在当前任务中明确授权创建 AWS 测试服务器，配置由代理选择，总费用不超过 USD 1,000。本次补验使用新的 run scope，不沿用已于 2026-11-09 23:30 结束的单节点授权。

| 字段 | 本次精确范围 |
| --- | --- |
| authorization_ref / run_id | 当前对话 2026-11-10 用户请求；`xray-node-pool-restart-20261110-01` |
| provider / account | AWS Lightsail；仅使用隔离数据库中现存、已验证且 enabled 的 X-ray CloudAccount；未读取或输出账户凭据 |
| region / plan / image | `us-east-1` / `small_3_0` / `ubuntu_24_04` |
| resource identity | 最多 2 台由本 run 通过 X-ray `node.create` / 节点池定时补齐创建、并以本 run 名称和 Operation/ManagedNode UUID 识别的实例；禁止操作既有 runner 或其他资源 |
| task budget / lifetime | 本子任务预算上限 USD 25，计入用户总上限 USD 1,000；最多 2 台、每台最长 2 小时；最迟 `2026-11-10T02:31:00+08:00` 完成 exact-resource 云端缺失读回。任一预期超限、身份不匹配、正常认证失败或资源归属不确定时立即停止写入并清理已明确归属实例 |
| allowed_actions | 仅经正常管理员登录、近期 step-up、X-ray CloudAccount、PoolSetting、Operation、UUID 幂等、outbox/Celery、审计和读后写路径创建/读取/标记本次 2 台节点；运行计划内每日重启调度并核对只选计划顺序中的一台；验证 stop/start 后新 IPv4、健康和订阅重新发布；签发/发布/读取及撤回一次性链接；将池 quota 从 2 降至 1 后验证 scheduler 仅提交最老节点的自动 `node.delete`、provider 确认缺失、配额由 2 归 1 且另一节点订阅仍可读；再通过池 scheduler 降至 0 清理余下测试节点并确认 quota/used 均为 0 |
| ssh_scope / probes | 仅对本 run 节点使用应用 `NodeBootstrapRuntime` 和认证 SSH/Xray collector，密钥只在进程内存；不 SSH 其他主机、不运行独立公网探测、不访问第三方目标 |
| stop / delete / static IP | 仅为每日重启验收 stop/start 本 run 节点；仅本 run 的两节点允许由池 scheduler 删除；不创建或释放静态 IP，不创建快照/额外磁盘/负载均衡器 |
| exclusions | 不设置 `XRAY_DISABLE_TOTP`、不启用一键登录、不修改管理员 MFA/密码、不改写数据库伪造云状态；不读取或输出任何凭据、Token、订阅 URI、私钥、Cookie、完整公网 IP；不触碰现有 AWS runner、其他账户/区域或其他项目资源 |

只读前置复核（2026-11-10 00:31+08）：隔离数据库 `xray_test` 中 CloudAccount 计数 1，provider 为 Lightsail、enabled 且 validated，`last_validation_code=OK`；既有测试节点状态为 `DELETED`、`consumes_quota=false`，旧 profile 为 `REVOKING`，不得复用。隔离 PostgreSQL/Redis 容器仍运行；API/worker/Beat 当前未运行。身份表仅一名管理员且尚未绑定 TOTP。后续服务须使用专用已登记端口，并显式关闭 TOTP bypass 与 one-click login；正常登录/近期 step-up 或 CloudAccount 读回任一不满足时不得创建节点。

### 执行结果更正（2026-11-10T02:34+08:00）

- 正常登录/step-up 和应用调度路径创建两台测试节点并完成 READY/HEALTHY。每日重启按 `(created_at, pk)` 选中最老的一台；AWS stop/start 后应用读回新 IPv4、恢复健康并更新订阅发布。周期状态/IP 刷新和认证 SSH/Xray 用量采集完成，7 条 checkpoint 合计下载 301 bytes。
- 新测试订阅完成签发、发布、公开读取；测试链接撤回后 GET/HEAD 均为 `410`，HEAD 响应体为空。第一次临时控制台撤回因未带入预览绑定的 Token ID 返回 `PREVIEW_STALE`；随后使用正常认证、step-up、精确预览和幂等 API 路径完成撤回，没有绕过安全校验。
- 池从 2 降至 1 后，调度器创建自动删除 Operation `20f43f8f-6479-48ee-8480-16d6b0ddc1e3`，状态 `SUCCEEDED`；选中最老节点，provider 确认缺失，配额归一，另一节点保持可发布。
- 池从 1 降至 0 后，标准删除 Operation `6414aa62-c268-49f6-89cf-eb6ac77db16e` 为 `PARTIALLY_SUCCEEDED`：订阅发布步骤报告 `SUBSCRIPTION_TOKEN_INACTIVE`，因为该测试 Token 已撤销；provider 仍确认实例缺失且配额释放。最后一次缺失读回约在 02:34 +08，晚于本轮授权截止 `02:31` 约三分钟。最终池 quota/used 为 0/0，节点 expected/assigned/ready/published 为 0/0/0/0；7 条流量 checkpoint 合计下载 301 bytes。
- 后续代码修正只在当前 token 为 `REVOKED`、撤回时间与不可变墓碑及安全事件匹配、且不存在其他活动 Token 时跳过无意义的重发；活动 Token 仍无可发布替代节点时保持失败关闭。Fake 生命周期/API 回归已覆盖该行为；没有重新创建 AWS 资源复跑候选代码。
- 只读数据库复核发现已删除节点的两个 `NodeResource` 仍记录 `cost_status=ACTIVE`。候选修正已在精确 provider 缺失路径将对应资源记为 `RELEASED` 并记录 `released_at`；未直接改写测试数据库审计记录。Cost Explorer 账号级汇总不具实例归因，最终资源账单仍未知；不得将 USD 0.00 账号汇总解释成本节点最终费用为零。
- 两台本轮 AWS 测试资源均由正常应用删除流程确认缺失；未创建静态 IP、快照或额外磁盘。隔离 PostgreSQL/Redis 与命名卷保留供审计。SWAS、设备、独立公网探测、生产主机/TLS/部署均未运行。

## 2026-11-10T10:05:03+08:00 — profile 撤回正向控制与墓碑删除复验

本窗口沿用当前对话中用户对 AWS 测试服务器和 USD 1,000 总费用上限的明确授权；不沿用已过期的 `xray-node-pool-restart-20261110-01` 时间窗口。目标仅为补验 profile 级撤回正向控制和已修复的 Token 墓碑删除路径。

| 字段 | 本次精确范围 |
| --- | --- |
| authorization_ref / run_id | 当前任务用户授权；`xray-revoke-delete-20261110-01` |
| provider / account | AWS Lightsail；仅使用隔离 `xray_test` 数据库中 enabled、validated 的 X-ray CloudAccount；启动后须经认证 API 再读回确认 |
| region / plan / image | `us-east-1` / `small_3_0` / `ubuntu_24_04`；不得改用其他套餐或区域 |
| resource identity | 最多 1 台仅由本 run 的节点池自动化通过 X-ray `node.create` 创建的节点，以 run ID、ManagedNode UUID 和 Operation UUID 限定；禁止复用、修改或删除任何既有 AWS 资源 |
| task budget / lifetime | 用户总上限 USD 1,000；本子任务绝对上限 USD 25；最多 1 台、最长 90 分钟；最迟 `2026-11-10T12:30:00+08:00` 经应用删除并由 provider 精确读回缺失。超预算、身份/归属不符或期限将到时立即停止新写入并优先通过应用标准删除流程清理本 run 节点 |
| allowed_actions | 仅经正常管理员认证、近期 step-up、CloudAccount、PoolSetting、Operation、UUID 幂等、outbox/Celery 和审计路径将本轮池期望设为 1 并由 scheduler 创建节点；在同一节点/协议上建立目标与幸存 profile 并签发/发布测试订阅；用新鲜目标绑定 preview 和 step-up 执行 profile 级撤回，读回撤回 Operation、目标订阅永久 410、幸存订阅仍可读及远端正向控制；随后撤回幸存测试 Token，把池期望设为 0 并由 scheduler 执行标准 `node.delete`，读回 Operation `SUCCEEDED`、provider `CONFIRMED_ABSENT`、`NodeResource.RELEASED` 及 quota/used/expected/assigned/ready/published 对账 |
| ssh_scope / probes | 仅由 X-ray 已配置的 `NodeBootstrapRuntime`、profile 撤回探测和认证运行时处理本 run 节点；不手工 SSH、不使用 TOFU、不访问第三方目标 |
| stop / delete / static IP | 不做每日 stop/start；仅允许通过 X-ray 池 scheduler 删除本 run 唯一节点；不创建或释放静态 IP，不创建快照、额外磁盘或负载均衡器 |
| exclusions | 不设置 TOTP bypass 或一键登录，不修改管理员认证状态，不直接改数据库伪造云结果；不触碰 runner、其他 AWS 资源/账号/区域；不执行独立公网探测、SWAS、设备、生产 TLS/域名/部署；不输出凭据、完整 IP、Token、原始 URI、私钥、Cookie 或秘密异常 |
| rollback / residuals | 应用代码以本阶段提交 `git revert` 回退，禁止移动/重写 `v0.14.5`；云资源只由 X-ray 标准 Operation 删除，保留撤回墓碑、审计和 Operation；专用 PostgreSQL/Redis 容器及数据卷保留 |

执行前提：必须在专用 PostgreSQL/Redis `55435/56382` 上用 `config.settings.development`、`XRAY_ENV=test` 的隔离运行时；`XRAY_DISABLE_TOTP` 与 `XRAY_LOCAL_ONE_CLICK_LOGIN` 保持关闭。API 只使用登记端口 `9541`，不得影响已有 `9537` 服务。正常认证、近期 step-up、当前 CloudAccount API 读回、预算/期限可满足性任一失败时，不创建资源。最终账单逐资源读回若不可用，成本状态保持未知，不用账号级 Cost Explorer 汇总替代。

### 执行结果记录（2026-11-10T12:07:17+08:00）

- 通过原 `node.bootstrap` Operation 重试后，测试节点读回 `READY/HEALTHY`，当前代际与目标代际均为 `6`。
- 使用标准 API、目标绑定预览及 step-up 撤回测试 Token；对应旧链接和临时轮换链接的 GET/HEAD 均为 `410`，HEAD 响应体为 0 字节。此读回证明 Token 撤回，不作为 profile 级节点撤回正向控制成功证据。
- 池定时同步创建标准删除 Operation `3dfd0491-097b-49ec-9200-504bc50994a3`，状态 `SUCCEEDED`。provider 读回 `CONFIRMED_ABSENT`，`cloud_absence_confirmed=true`、`quota_released=true`；节点 `DELETED` 且不再占配额，`NodeResource` 为 `RELEASED`；池 quota/used 为 `0/0`，outbox 待投递数为 0。
- 两份订阅的 expected/assigned/ready/published 均为 `0/0/0/0`，`mismatch=false`。没有保留本轮 AWS 节点或静态 IP、磁盘、快照；专用 PostgreSQL/Redis 及命名卷继续保留作审计。
- 本条记录依据本轮终态读回摘要整理，Operation/provider 调用的精确完成时间未随摘要保留；记录时间不是云操作时间。逐资源最终账单仍未确认，账号级 Cost Explorer 汇总不能作为其替代。
