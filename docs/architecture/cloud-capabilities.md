# 双云能力矩阵

核对日期：2026-09-17。SDK 锁定版本见 `backend/uv.lock`：boto3/botocore 1.43.95、SWAS SDK 4.0.0、阿里云 STS SDK 1.2.0。

| 能力 | AWS Lightsail | 阿里云 SWAS | document | stub | live | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| 身份验证 | SUPPORTED | SUPPORTED | yes | yes | no | 仅显式凭据；禁止默认凭据链 |
| 区域/套餐/镜像 | SUPPORTED | SUPPORTED | yes | yes | no | 价格缺失显示 unknown，不显示 0 |
| 建机/查找 | SUPPORTED | SUPPORTED | yes | yes | no | 管理员 Operation + 确定命名/标签 |
| 启停/重启 | SUPPORTED | SUPPORTED | yes | yes | no | SDK 受理不等于动作完成 |
| 删除实例 | SUPPORTED | SUPPORTED | yes | yes | no | 必须另行授权并复核归属 |
| 防火墙 | SUPPORTED | SUPPORTED | yes | yes | no | 规则回读与数据面隔离分开判定 |
| 原地换 IP | UNVERIFIED | UNSUPPORTED | partial | partial | no | AWS 待 P3 多步骤 checkpoint；SWAS 使用替代节点 |
| 静态 IP 释放 | UNVERIFIED | UNSUPPORTED | partial | no | no | 与删机分离确认 |
| 重装 | UNVERIFIED | UNVERIFIED | no | no | no | 不作为第一阶段可用按钮 |
| 退款/停止计费 | UNVERIFIED | UNVERIFIED | no | no | no | 停机不代表停止收费 |
| IPv4/IPv6 TCP/UDP 隔离 | UNVERIFIED | UNVERIFIED | partial | partial | no | 无真实数据面证据不得写为隔离完成 |

## 本地边界

默认 `XRAY_ENABLE_PROVIDER_NETWORK=0`，账号创建/验证会以 `CLOUD_NETWORK_DISABLED` 失败；只有显式授权环境才允许尝试 SDK 网络调用。所有本地契约测试注入 Mock/Stub client，未读取 AWS profile、阿里云默认凭据链或实例元数据。

官方参考：

- AWS Lightsail API: <https://docs.aws.amazon.com/lightsail/2016-11-28/api-reference/Welcome.html>
- Alibaba Cloud SWAS OpenAPI: <https://api.aliyun.com/product/SWAS-OPEN>
- Alibaba Cloud STS GetCallerIdentity: <https://api.aliyun.com/api/Sts/2015-04-01/GetCallerIdentity>
