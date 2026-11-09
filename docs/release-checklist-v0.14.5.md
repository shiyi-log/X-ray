# v0.14.5 发布清单

## 本地验收

- [x] 同步 `VERSION`、后端/前端包、OpenAPI、Playwright 证据路径和安装器默认标签到 `0.14.5`。
- [x] 修复普通 Django 管理命令显式使用项目 Celery app 发布 durable outbox 任务，并保留 focused 回归。
- [x] 聚合验证一次性订阅签发、发布、公开 GET、重启后 IPv4、Token 撤回、GET/HEAD `410` 及空 HEAD 响应。
- [x] 使用专用 PostgreSQL/Redis 重跑 `scripts/check-local.sh`：业务候选 r3 为 19/19 gates exit 0、后端 531 passed/2 skipped；修复版本检查 SIGPIPE 后的 r6 为 19/19 gates exit 0、后端 532 passed/2 skipped、前端 88 passed、Playwright 8 passed；acceptance、boundary、secret、skill 均通过。两个 skip 需要可丢弃 Linux/systemd 主机。证据：`artifacts/acceptance/0.14.5/final-gates-20261110-r6/`。
- [x] 聚焦回归复跑：40 passed、1 skipped；唯一 skip 是需要可丢弃 Linux 主机的一键安装运行时集成。
- [x] SecretMaskFilter 对 `/s/<token>` 请求路径脱敏；日志 focused 测试先 RED 后 GREEN，未记录任何原始 Token。
- [x] 新增池调度跳过游标、配额释放后的订阅节点计数、资源释放状态和已撤销 Token 发布回归；focused 生命周期/发布测试 8 passed。

## 真实云验收

- [x] 通过正常 CloudAccount/Operation/outbox/Celery/审计/读后写路径补齐两台测试节点，并完成按 `(created_at, pk)` 选最老节点的每日 stop/start、动态 IPv4、健康、状态/IP 刷新、订阅重发及 7 条流量 checkpoint（下载合计 301 bytes）。
- [x] 池从 2 降到 1 后自动删除最老节点，Operation `20f43f8f-6479-48ee-8480-16d6b0ddc1e3` 为 `SUCCEEDED`；计数与余下节点订阅读回一致。
- [x] 验证一次性订阅签发/公开读取/撤回；撤回后同一链接 GET/HEAD 均为 `410`，HEAD 无响应体。
- [x] 池降至 0 后第二台节点通过标准删除路径完成 provider 缺失读回、配额释放，最终 `quota/used=0/0`，节点计数为 `0/0/0/0`，无静态 IP/快照残留。原删除 Operation `6414aa62-c268-49f6-89cf-eb6ac77db16e` 因当时对已撤销 Token 尝试重新发布而为 `PARTIALLY_SUCCEEDED`；当前代码对此增加带墓碑校验的无操作处理，Fake 回归通过，未在 AWS 重跑。
- [ ] 首轮 profile 级撤回仍为 `REVOCATION_UNCONFIRMED`，其 fail-closed 自动删除没有取得正向成功证据；双节点补验的最终清理读回约在 02:34 +08，晚于授权截止 02:31 约三分钟。逐资源最终 AWS 账单未知，不能报告为 USD 0。

## 公开发布

- [x] 推送候选 `e38b48b5f4b63795595ed9ff52f10a76b91ffb6f` 到 `main` 并确认 X-ray delivery gates run `42681779767` / job `129377918267` 成功；上一次旧提交因固定 jq 下载 HTTP 504 失败，未复用为通过证据。
- [x] 修复交付脚本长版本输出触发 SIGPIPE 的问题；main commit `0353513271e139ab6a2d7c9f1753d82675ea828d` 的 Delivery Gates run `42692116452` / job `129414242630` 成功。
- [x] 创建并推送 annotated `v0.14.5`；tag object `780919d3512c937ef1e7483f6fc4b138a4e0020d` peeled 到候选提交。
- [x] 从 `main` 手动运行 Release workflow：run `42694179688` / job `129421511925` 成功。GitHub Release `439611923` 于 `2026-11-10T04:34:27+08:00` 发布，非草稿、非预发布；tag peeled 到 `e38b48b5f4b63795595ed9ff52f10a76b91ffb6f`。实际下载的三项 SHA-256 与 GitHub asset digest 一致：tarball `662c6ca60b4acd4913fc5d02de1018f2508a987c9f7b8db6ddfd83883f81740e`、manifest `011a928b83b541364b98a6ad132a772e95aec9afe2d58303179e8e0683905aba`、`SHA256SUMS` `91dcd60d0c8187327241557c31e8a00cdc6f2ab3584721748d183cc1b9e24f86`；校验文件中的 tarball/manifest 摘要与下载内容一致。

## 外部边界

- [ ] SWAS、Shadowrocket 真机、公网探测、生产镜像切换和生产部署未运行。

## 回退

应用回退使用 `v0.14.4` 或对本阶段相干提交执行 `git revert`。不反向迁移，不恢复已撤销 Token、凭据、安全事件或云操作状态；保留本轮审计和云清理证据。
