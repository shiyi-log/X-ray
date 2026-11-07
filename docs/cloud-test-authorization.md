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
