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
