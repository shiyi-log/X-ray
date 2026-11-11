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

## 2026-11-10T15:48:17+08:00 — profile 撤回验收续期与前置阻塞

用户于当前对话明确续期 90 分钟，范围限一台 `us-east-1` Lightsail `small_3_0`
Ubuntu 24.04 测试节点、额外预算上限 USD 25，继续计入总预算 USD 1,000。
窗口为 `[2026-11-10T15:48:17+08:00, 2026-11-10T17:18:17+08:00)`。
此续期不扩大到其他账号、既有资源、区域或套餐，也不豁免 X-ray 管理平台认证、
step-up、CloudAccount 身份匹配及读后写证据要求。

只读预检于 2026-11-10 15:49 至 15:54+08 执行后，本授权保持有效但**未进入云写阶段**：

- AWS CLI `sts get-caller-identity` 成功，但当前 caller account 摘要
  `sha256:e9502bcd3047` 与本授权既有账号摘要 `sha256:94a91b85428b` 不匹配。
- Lightsail `GetInstances`、`GetBundles`、`GetBlueprints` 与 Cost Explorer
  `GetCostAndUsage` 均返回 `AccessDenied`（CLI exit 254）；当前实例数量、资源归属与
  逐资源最终费用未知。
- 本地 API `127.0.0.1:9541/health/ready` 返回 HTTP 200，但认证 session 显示
  `authenticated=false`；系统和 CloudAccount 管理 API 在无 session 下分别返回
  HTTP 401。管理员认证、step-up 和当前 CloudAccount 无法验证。
- 未创建或修改 AWS 资源；未执行 AWS/SSH 写入、删除或 IP 操作。不得通过 AWS CLI、
  手工 SSH、数据库写入或其它方式绕过 X-ray 标准流程。

因此本次续期授权**被账号归属不匹配、AWS 只读 AccessDenied、管理 API 未认证三项前置
条件共同阻塞**。在账号摘要由管理员核实并恢复授权账号读取权限、且标准管理员会话、
step-up 与已验证 CloudAccount API 读回成功之前，不得创建该节点。窗口到期后本次
续期自动失效；当前资源清单和最终账单仍未知，不能宣称已清理或费用为零。

## 2026-11-10T16:23:42+08:00 — 续期账号/CloudAccount 身份核对更正

本节追加更正上节及 `xray-aws-renewal-20261110-01/001` 的当前身份/权限读回；保留旧记录。
当前续期窗口仍有效至 `2026-11-10T17:18:17+08:00`，但新读回没有解除身份前置条件：

- 2026-11-10 16:18+08，显式 `AWS_PROFILE=root` 的 STS 成功（exit 0），账号摘要为
  `sha256:4a0ef08458dd`，与本续期授权记录要求的 `sha256:94a91b85428b` 不一致。
  上节提到的 `sha256:e9502bcd3047` 是 default profile，不代表显式 root profile。
- 同一 root profile 对 `us-east-1` Lightsail 的 `GetInstances`、`GetBundles`、
  `GetBlueprints` 均成功（exit 0）：该 profile 当前实例清单计数为 0；`small_3_0`
  目录价为 USD 12/月、2 vCPU/2 GiB；`ubuntu_24_04` blueprint 为 24.04 LTS。
  这些读数来自与本次授权不匹配的账号，不能作为授权账号的资源清单或费用证据。
- 未对不匹配账号查询 Cost Explorer。该续期授权账号的实例数、单资源费用与最终账单
  仍未知；不以账号级汇总或其他账号的价格目录替代。
- `127.0.0.1:9541/health/ready` 为 HTTP 200；当前 auth session 为
  `authenticated=false`，CloudAccount collection 为 HTTP 401。没有管理员 session，
  因此当前 CloudAccount、step-up 和账号验证状态未能读回。此前文档中的
  CloudAccount 摘要 `sha256:4a0ef08458dd` 仅作历史身份线索，不能代替当前 API 验证。
- 没有创建/修改 AWS 资源，没有 AWS 写入、SSH、删除、IP 操作、Cost Explorer 查询、
  CloudAccount 凭据更换或数据库写入。不得直接 AWS CLI 写入或替换 CloudAccount 绕过流程。

当前结论仍为**续期有效但云写入被阻塞**：授权账号摘要 `94a91b85428b` 与显式 root
profile `4a0ef08458dd` 不符，且管理 API 未认证。恢复标准管理员认证/step-up 并使当前
已验证 CloudAccount 与授权账号一致之前，不创建测试节点。若无法在截止前解除阻塞，
窗口于 `2026-11-10T17:18:17+08:00` 自动失效；逐资源最终费用保持未知。

## 2026-11-11T00:30:03+08:00 — 测试节点验收授权续期与匹配复核

用户于 2026-11-11 00:30:03+08 明确续期 90 分钟：最多一台 `us-east-1`
Lightsail `small_3_0` Ubuntu 24.04 测试节点，新增费用上限 USD 25，累计任务费用
仍不得超过 USD 1,000。有效窗口为 `[2026-11-11T00:30:03+08:00,
2026-11-11T02:00:03+08:00)`。用户声明本机已切换匹配 profile，管理员登录及
step-up 已完成；这些声明需要当前 STS/API 读回支持后才可执行云写入。

2026-11-11 00:56 至 01:09+08 的只读复核结果：

- `aws configure list-profiles` 仅列出 `default`、`root`。两者 STS 成功，但账号摘要
  分别为 `b1746f68f5be`、`4a0ef08458dd`，都不匹配授权摘要 `94a91b85428b`；
  没有发现所称匹配 profile。
- 显式 `AWS_PROFILE=root` 的 `us-east-1` Lightsail 清单为 0；`small_3_0` 目录价
  USD 12/月、2 vCPU/2 GiB，`ubuntu_24_04` 为 Ubuntu 24.04 LTS。上述读数属于摘要
  `4a0ef08458dd` 的非授权账号，不代表授权账号的资源目录或资源状态。
- `root` profile 对 2026-11-01 至 2026-11-12 的 Amazon Lightsail Cost Explorer
  月内累计只读金额为 USD 6.0243037302。此值是整个账号且 profile 身份不匹配，
  不能归因本测试、证明预算余额或确认最终账单；授权账号的资源级费用仍未知。
- 浏览器页面 `http://127.0.0.1:9538` 的认证 session 明确返回
  `authenticated=false`、`recent_auth_until=null`。CloudAccount API 无有效会话时为
  HTTP 401；当前管理员登录、step-up 和应用 CloudAccount 账号匹配均未验证。登录页
  已保留为 handoff，未读取或代输认证值。API readiness 为 HTTP 200。
- 未对任何 profile 执行写操作、SSH、实例删除或 IP 操作；未查询授权账号账单，未改
  CloudAccount 凭据或数据库，没有创建测试节点。

因此续期窗口当前尚未结束，但**云写入在授权窗口内被 profile 账号不匹配和应用未
认证共同阻塞**。只有匹配账号的 STS/资源与费用只读读回、浏览器认证/step-up 以及
应用 CloudAccount 校验都成功后，才能经 X-ray 标准预览、幂等 Operation 与读后写链路
执行限定的一台测试节点；窗口于 `2026-11-11T02:00:03+08:00` 到期，之后必须重新授权。

## 2026-11-11T01:52:57+08:00 — 匹配 profile 更正及本地测试收尾

本节追加更正上节的 AWS profile 身份读回，并记录本地回归结果；不删除或覆盖前述
历史观察。授权窗口为 [2026-11-11T00:30:03+08:00, 2026-11-11T02:00:03+08:00)，
按本机 UTC 时钟 2026-11-10T17:52:57Z 换算为上海时间 2026-11-11T01:52:57+08:00，
此记录时间仍在窗口内。

- AWS_PROFILE=root 的 STS 账号摘要为 94a91b85428b，与本次授权账号摘要一致；
  AWS_PROFILE=root aws lightsail get-instances --region us-east-1 返回实例数 0。
  未尝试创建或修改资源。small_3_0 价格目录与账号级账单尚未重新核实，不据此声称
  预算余额或最终费用。
- 只读检查本机 X-ray session：端口 9537、9538、9541 的
  /api/v1/auth/session 均为 HTTP 200，但都返回 authenticated=false、
  mfa_enabled=false、recent_auth_until=null；三个实例的 CloudAccount collection
  均返回 HTTP 401。9537 /health/ready 返回 503；9541 /health/ready 为 HTTP 200。
  未读取或输入管理员密码、TOTP、Cookie、Token，也未启用测试旁路。
- 没有可验证的管理员 session/近期 step-up/CloudAccount，因此不经 AWS CLI 或直接
  数据库绕过 X-ray 标准流程执行真实云写入。真实 profile 级撤回正向控制、节点数量、
  流量和逐资源最终账单本轮均未运行；AWS 总体验收保持 blocked。
- 新增自动化集成回归 test_daily_restart_handler_reads_new_ip_health_and_republishes_subscription，
  使用 Fake provider 和独立 PostgreSQL/Redis project，串联每日 stop/start scheduler、
  标准 Operation handler、动态 IP 更新、健康探测，以及可用订阅格式的新地址发布。
  聚焦用例 1 passed；自动化测试文件 33 passed；全后端 426 passed、2 skipped（固定
  Xray binary 未配置）。Ruff、验收矩阵、边界、秘密、技能、JSON 和 diff 门禁均通过。
- 此次没有运行时代码修改，版本仍为 v0.14.6；不为测试/审计增量创建新版本、tag
  或 Release。真实 AWS 验收和相应新版本发布未完成。

## 2026-11-11T02:00:42+08:00 — 本次续期授权窗口结束

按执行机器实际 UTC 时钟 2026-11-10T18:00:42Z（上海时间 2026-11-11T02:00:42+08:00），
本次 90 分钟 AWS 测试节点授权已到半开区间终点并过期。窗口内未创建任何 AWS 节点，
未执行 AWS 写入、SSH、删除、IP 操作或真实 profile 撤回。AWS profile 身份匹配，
但本机 X-ray 管理 session/step-up/CloudAccount 前置条件没有通过；之后任何真实云动作
需重新取得用户授权并重新验证管理员身份与费用边界。逐资源最终费用、真实节点/流量核对
及撤回正向控制仍为未知/未运行。

## 2026-11-11T02:30:13+08:00 — 新 90 分钟授权与认证前置阻塞复核

用户在当前对话再次明确授权：最多一台 `us-east-1` Lightsail `small_3_0` Ubuntu 24.04
测试节点，额外费用上限 USD 25，总费用仍不超过 USD 1,000。为避免沿用此前已过期
窗口，本次保守以用户授权消息后的首次机器时钟读数 `2026-11-11T02:12:09+08:00` 为
窗口起点，有效半开区间 `[2026-11-11T02:12:09+08:00, 2026-11-11T03:42:09+08:00)`。

只读复核于 02:12–02:13+08 完成：

- 显式 `AWS_PROFILE=root` 的 STS account stdout（含 CLI 终止换行）按既有
  `shasum -a 256` 流程生成的摘要前缀为 `94a91b85428b`，与本次授权摘要匹配；
  对同一 account 文本去除换行后计算得到 `4a0ef08458dd`，该值不是本项目既有授权
  指纹格式。`us-east-1` Lightsail `GetInstances` 返回 0 台。未发出云写请求。
- `127.0.0.1:9538/login?redirect=/overview` 仍显示管理员登录表单。端口 9537、
  9538、9541 的 auth/session 均 HTTP 200、`authenticated=false`、
  `mfa_enabled=false`、`recent_auth_until=null`；各 CloudAccount collection 均 HTTP 401。
  因此管理员登录、step-up 和 X-ray CloudAccount 匹配均未通过当前 API 读回。
- 未读取、输入或保存认证秘密；未使用认证旁路。未创建 AWS 资源，未执行 AWS 写、SSH、
  删除、静态 IP 操作或费用查询；套餐目录、逐资源费用和最终账单尚未核实。

结论：本授权窗口有效，但真实验收仍在 X-ray 认证/CloudAccount 门槛前阻塞；AWS profile
匹配不足以开始写入。管理员完成正常登录和近期 step-up 后，还需重新读回已验证
CloudAccount、AWS 账号、实例清单与费用边界，再经标准预览、幂等 Operation 和读后写
流程继续。若这些门槛未在窗口结束前通过，本授权自动失效，不执行云写。

## 2026-11-11T17:49:19+08:00 — 授权过期后的发布候选只读状态

此事件在前述续期窗口 [2026-11-11T02:12:09+08:00,2026-11-11T03:42:09+08:00) 之外记录。未沿用云测试授权，未执行 AWS/SWAS 写入、SSH、公网探测、删除、静态 IP、认证/数据库写入或费用查询。最新可用的 canonical SHA-256(精确 STS Account 字段文本)指纹为 default=sha256:b1746f68f5be、root=sha256:4a0ef08458dd，均不等于授权摘要 sha256:94a91b85428b；X-ray 管理员 session、recent step-up 与 CloudAccount 当前无新的已认证浏览器/API 读回。故 AWS 资源数、逐资源成本及最终账单未知，完整真实云验收保持 blocked/not-run。用户原请求中的 GitHub 版本发布授权仍可用于非生产交付，不能将代码发布表述为 AWS 验收或生产部署。

本轮 candidate worktree 完整本地门禁记录于 artifacts/acceptance/0.14.7/final-gates-20261111-release-r2/summary.tsv：19/19 gates exit 0；后端 JUnit 553（551 passed、2 skipped），前端 88 passed、Playwright 8 passed；两项跳过需可丢弃 Linux/systemd 主机。初次路径选择了 pnpm 11.25.0，runtime gate exit 1，未运行后续检查；改用缓存中的 Corepack pnpm 10.33.0 后完整通过。隔离 xray-usage-retry-20261111 容器和网络已停止，PostgreSQL/Redis 命名卷保留。该证据仅是本地 Fake/Stub/容器验证；尚无本版本源码提交、远端 CI、tag 或 Release 读回。

### 身份指纹算法追加更正 — 2026-11-11T02:45:27+08:00

上节对比 STS CLI stdout 整行（包含终止换行）得到的 `94a91b85428b` 与历史授权指纹
算法不一致，故上节“root 身份匹配”的结论撤销。项目历史记录明确按 STS `Account` 字段
文本本身计算 SHA-256 前缀；不包含 CLI 输出换行。按同一规范重查当前所有 profile：
`default=sha256:b1746f68f5be`、`root=sha256:4a0ef08458dd`，都不匹配授权账号
`sha256:94a91b85428b`。命令输出行的摘要与账号字段的摘要不是同一个 fingerprint，
此处保留是为了说明先前误判来源，不得用作身份匹配证据。

`root` profile 的 Lightsail `us-east-1` 清单仍为 0，但该 profile 不是授权账号，不能确认
授权账号的实例数量。当前管理员登录页仍在，9537/9538/9541 session 未认证且
CloudAccount=401；无管理员、step-up、CloudAccount 和 AWS 账号的共同校验。没有尝试云写、
SSH、删除、IP 操作或费用读取。当前 AWS 验收保持 `blocked`，授权窗口虽记录至
`03:42:09+08`，任何云写均须先解决上述阻塞并在该半开窗口内重新验证所有前置条件。

## 2026-11-11T03:01:44+08:00 — 用户声明 profile/step-up 已就绪后的重新核验

用户声明继续使用授权账号 `94a91b85428b`、本机已切换匹配 profile、X-ray 管理员登录
与 step-up 已完成，并续用最多一台 `us-east-1 small_3_0 Ubuntu 24.04` 节点、额外
USD 25、总额不超过 USD 1,000 的 90 分钟授权。消息中的起始时间仍为占位符；按本次
收到说明后的首个实际 UTC 时钟读数 `2026-11-10T19:01:44Z` 保守起算，窗口记录为
`[2026-11-11T03:01:44+08:00, 2026-11-11T04:31:44+08:00)`。

本轮只读核验结果：

- 工具执行环境中 `AWS_PROFILE`、`AWS_DEFAULT_PROFILE` 均未设置；`aws configure
  list-profiles` 只列出 `default` 与 `root`。按项目既定 SHA-256(精确 STS Account
  字段文本) 算法，默认身份摘要为 `b1746f68f5be`，显式 `root` 为
  `4a0ef08458dd`，均不匹配授权账号 `94a91b85428b`。用户所称匹配 profile 未在
  本次工具环境中识别；不读取/显示凭据。
- 端口 9537、9538、9541 的无凭据 HTTP GET `/api/v1/auth/session` 均返回 200，
  body 字段为 `authenticated=false`、`mfa_enabled=false`、`recent_auth_until=null`；
  无凭据 CloudAccount GET 均为 HTTP 401。这些是无浏览器 Cookie 请求，不能据此推断
  Chrome 中的已登录状态。Chrome 标签枚举未发现 X-ray 标签；打开 Chrome X-ray 页时，
  自动化接口报告另一个扩展 UI 正阻挡控制。未查看或操作该扩展 UI，也未访问/提取
  Cookie、管理员密码、TOTP 或 CloudAccount 凭据。step-up 与 CloudAccount 身份目前
  无法从浏览器或 API 独立读回。
- 9538、9541 readiness 均 HTTP 200；9537 readiness 为 HTTP 503。AWS 当前授权账号
  的实例数、套餐价格、资源级费用和最终账单未能读回。未执行 AWS 写入、SSH、删除、
  IP 操作、Cost Explorer 查询、认证写或数据库写。

因此即使用户声明登录和 step-up 完成，当前执行环境仍不能独立证明匹配 AWS 身份及
CloudAccount。90 分钟窗口内不绕过标准 X-ray 流程执行云写入；需先关闭 Chrome 扩展
阻挡并告知匹配 profile 名称，再由正常浏览器/API 读回 session、recent step-up、
CloudAccount 账号摘要，并再次确认该 profile 的 AWS 身份和费用边界。未完成时窗口
到期自动失效。
