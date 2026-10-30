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
| 0.5.0 | P5 | `fd23a514a03ae50c3943c0bd6a890fe1533b623a` / `ee02808a50df0f1c4c1297b635ef95342c268cfa` / `de1ab0b1ff6c628415bb5b38ed6cd1133e880650` | `v0.5.0-console` | 2026-09-17 | 无新增业务迁移；test Cookie 名仅用于 HTTP E2E | 120 backend/installer/revocation tests; 11 frontend unit; 6 real-browser E2E; OpenAPI deterministic; typecheck/lint/build/Ruff/migration/boundary/secret gates passed | real cloud/SSH/public probe/production `blocked`; Shadowrocket device `not-run` | `v0.4.0-subscriptions` |
| 0.6.0 | P6/P6.3 | `69a6301` / `ad30634` / `e047495` / `c229c7fcf2574d3a024420da686b4abe4ef6ddc0` / `a5ff96e239c70b2b7c43d6c3e9f12bd96c588561` / `5cdeb704b80e2d0dab56efc2b6687f5ab6e720c7` / `353eb259f7b4aa4ebe7c762d0f8db698ab621ea0` / `6c8099d21462964237eb19e9b030faaa6cf9bf0c` / `924cd3d9741bc66bfee2cd72ec89752f3d0e2070` | `v0.6.0-delivery` | 2026-09-17 | subscriptions 0004；expand-only，无破坏性迁移 | 19 gates passed on source candidate `924cd3d...`; 181 backend/installer/deploy/recovery tests with 0 skipped; 11 frontend unit; 7 Chrome E2E; Compose/images/OpenAPI/Xray/formats/static gates passed at `2026-09-17T19:59:55+08:00` | real cloud/SSH/public probe/production `blocked`; device/CI `not-run`; deletion/IP release `risky_not_executed` | `v0.5.0-console` |
| 0.7.0 | Release/installer/hot-update | `2c021ba25cb1c819948a9528617759b93b21f15d` / `8f7f21d752d3db39580bac40625f1bdd72597e84` | `v0.7.0` | 2026-10-29 | 无新增数据库迁移；版本元数据与 OpenAPI 同步 | 安装器/发布包 `5 passed, 1 skipped`; 前端单测 `40 passed`; typecheck/build/boundary/acceptance validator passed; GitHub Release 已手动创建并上传 3 个资产；自动 workflow 因账户计费阻断 | GitHub tag/release passed；匿名 raw bootstrap 因仓库 private 返回 404；real production image switch, SSH and public browser acceptance `not-run` | `v0.6.0-delivery` |
| 0.8.0 | Console redesign/release | `7a93596775a7da1ec08126e6c4e691c3c66b50e3` | `v0.8.0` | 2026-10-30 | 无新增数据库迁移；前后端/OpenAPI 版本元数据同步 | 前端单测 `46 passed`（15s timeout）；typecheck/lint/build passed；installer/deploy `35 passed, 5 skipped`；release package/checksums, uv lock, boundary, acceptance validator and diff passed；secret scan exit 1 with 2 historical ledger findings | GitHub tag/Release and 3 asset digests passed; Actions blocked before runner startup by account billing; private-repo anonymous bootstrap returned HTTP 404; production image switch, cloud, SSH and device acceptance `not-run` | `v0.7.0` |

P3 锁文件摘要：`backend/uv.lock` 为 `903eb25ec192a4181cff7e950b5e2fba11095fb76c2abcb44ae832b4c3e1e114`；`installer/manifest.json` 为 `2ed19fe494e91d0ece94c7d13c6851f5e55a14c817a401050ec12149f65a24bc`。固定 Xray 发行物缺失或摘要不匹配时安装门禁失败，不回退到在线 `latest`。

P4 锁文件摘要：`backend/uv.lock` 为 `0d84b8c84a81685b99b029ea809285c32b368fff3a1bcff4e2b8fcc3ab050696`；`installer/manifest.json` 为 `2ed19fe494e91d0ece94c7d13c6851f5e55a14c817a401050ec12149f65a24bc`；固定订阅解析 Compose 为 `bc3b1c67fd9f634eed7b905b64f787a432b46ff226c1c1e408a52b9254500bb0`。恢复或应用回退不得删除 Token tombstone、安全事件、已撤销凭据或云操作结果。

P5 锁文件摘要：`backend/uv.lock` 为 `0d84b8c84a81685b99b029ea809285c32b368fff3a1bcff4e2b8fcc3ab050696`；`frontend/pnpm-lock.yaml` 为 `1407eea1cf3de6cc8cdf711b15985f3ccce5399252eedda1dd9036ce433a048a`；`installer/manifest.json` 为 `2ed19fe494e91d0ece94c7d13c6851f5e55a14c817a401050ec12149f65a24bc`。Vben 固定上游和许可证见 `frontend/UPSTREAM.md`；浏览器证据见 `artifacts/acceptance/0.5.0/`。应用回退不得恢复已撤销 Token、凭据、云操作结果或安全屏障状态。

P6 锁文件摘要：`backend/uv.lock` 为 `247c08482f6f2c8193ff6e915c8a3a01ccab4b76a617e339559375c13a4c33e1`；`frontend/pnpm-lock.yaml` 为 `1407eea1cf3de6cc8cdf711b15985f3ccce5399252eedda1dd9036ce433a048a`；`installer/manifest.json` 为 `2ed19fe494e91d0ece94c7d13c6851f5e55a14c817a401050ec12149f65a24bc`。OpenAPI 与生成 TypeScript 摘要分别为 `8eb8ecc3eb7c3ef0ffeb6eb8666581c8ef29b8e1aa6bba223ad25a2653573940` 和 `ef497b2eca58ef59b02c6b36105af4e2a0eeeabd74927c25b476338cfc59bead`。

P6 本地镜像 ID：backend `sha256:c219bc15b6abbe24e40be12aec723d63c5b3183e74bb62c53ddd7e46190f75c9`、frontend `sha256:5a3c117ba9bfc53452be1d9fc7b309b122e29488810850bd5ce13d69d8d75b6f`、backup-tools `sha256:12c06b2a52040b3c634f160c52837ce3752849a610560750e62d4b1ce570fe7b`。完整清单见 `artifacts/acceptance/0.6.0/image-manifest.json`；这些是本机镜像 ID，不是 production registry 摘要。加密恢复测量见 `artifacts/acceptance/0.6.0/recovery-measurement.json`，本轮测试耗时 2.043s。

从 P6 回退应用时使用 `v0.5.0-console` 或对 P6 提交执行 `git revert`，并保持 subscriptions 0004 与安全账本向前兼容。不得回滚或删除 Token tombstone、撤销记录、云操作结果、已失效凭据或恢复安全屏障；从备份恢复必须进入新隔离目标并保持 `MAINTENANCE`，完成审计/撤销追平及全量凭据轮换后才能人工复开。

## 回退规则

1. 应用版本回退使用阶段标签或 `git revert <commit>`，不使用强制推送和硬重置。
2. 数据库只允许向前兼容迁移；回退应用不能恢复已撤销 Token、凭据或云资源状态。
3. 生产发布回退只切换已验证镜像；若迁移不可逆，先进入维护模式并执行对应恢复演练。
4. 恢复环境默认 `MAINTENANCE`，订阅返回 503，worker 禁止云写，直到审计追平和凭据轮换完成。
