# 版本与回退记录

本文件是 X-ray 管理平台的可追溯索引。每个条目必须记录版本、提交 SHA、标签、迁移状态、门禁命令、证据路径和回退点；没有证据的外部验收不得写成 `passed`。

## 记录格式

| 版本 | 阶段 | 提交 | 标签 | 日期 | 迁移 | 本地门禁 | 外部验收 | 回退点 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.0.0 | 基线 | `2da51e7` | `v0.0.0-baseline` | 2026-09-17 | 初始骨架 | `not-run` | `not-run` | `v0.0.0-baseline` |
| 0.0.1 | P0 | `2885503` | `v0.0.1` | 2026-09-17 | 无业务迁移 | runtime/skill/backend tests passed | `blocked` | `v0.0.0-baseline` |
| 0.1.0 | P1 | `fb0a2db` | `v0.1.0` | 2026-09-17 | identity 0001-0003 | 13 backend tests passed | `blocked` | `v0.0.1` |
| 0.2.0 | P2 | `851f8dd` | `v0.2.0` | 2026-09-17 | cloud_accounts 0001-0002 | 30 backend tests and static gates passed | `blocked` | `v0.1.0` |
| 0.3.0 | P3 | `f4975a7` | `v0.3.0-nodes` | 2026-09-17 | operations 0001; nodes 0001-0002 | 66 backend/installer tests, fixed Xray five-protocol runtime, Ruff, ShellCheck and static gates passed | real cloud/SSH/public probe `blocked` | `v0.2.0` |
| 0.4.0 | P4 | `aaf9913d4ed2eca5466c1b57f3c41f0228f029bd` | `v0.4.0-subscriptions` | 2026-09-17 | subscriptions 0001-0003 | 111 backend/installer/revocation tests; fixed parser, Xray, Ruff, ShellCheck, migration, boundary and secret gates passed | real cloud/SSH/public probe `blocked`; Shadowrocket device `not-run` | `v0.3.0-nodes` |

P3 锁文件摘要：`backend/uv.lock` 为 `903eb25ec192a4181cff7e950b5e2fba11095fb76c2abcb44ae832b4c3e1e114`；`installer/manifest.json` 为 `2ed19fe494e91d0ece94c7d13c6851f5e55a14c817a401050ec12149f65a24bc`。固定 Xray 发行物缺失或摘要不匹配时安装门禁失败，不回退到在线 `latest`。

P4 锁文件摘要：`backend/uv.lock` 为 `0d84b8c84a81685b99b029ea809285c32b368fff3a1bcff4e2b8fcc3ab050696`；`installer/manifest.json` 为 `2ed19fe494e91d0ece94c7d13c6851f5e55a14c817a401050ec12149f65a24bc`；固定订阅解析 Compose 为 `bc3b1c67fd9f634eed7b905b64f787a432b46ff226c1c1e408a52b9254500bb0`。恢复或应用回退不得删除 Token tombstone、安全事件、已撤销凭据或云操作结果。

## 回退规则

1. 应用版本回退使用阶段标签或 `git revert <commit>`，不使用强制推送和硬重置。
2. 数据库只允许向前兼容迁移；回退应用不能恢复已撤销 Token、凭据或云资源状态。
3. 生产发布回退只切换已验证镜像；若迁移不可逆，先进入维护模式并执行对应恢复演练。
4. 恢复环境默认 `MAINTENANCE`，订阅返回 503，worker 禁止云写，直到审计追平和凭据轮换完成。
