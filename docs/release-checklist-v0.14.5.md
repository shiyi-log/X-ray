# v0.14.5 发布清单

## 本地验收

- [x] 同步 `VERSION`、后端/前端包、OpenAPI、Playwright 证据路径和安装器默认标签到 `0.14.5`。
- [x] 修复普通 Django 管理命令显式使用项目 Celery app 发布 durable outbox 任务，并保留 focused 回归。
- [x] 聚合验证一次性订阅签发、发布、公开 GET、重启后 IPv4、Token 撤回、GET/HEAD `410` 及空 HEAD 响应。
- [x] 使用专用 PostgreSQL/Redis 重跑 `scripts/check-local.sh`：r3 19/19 gates exit 0；后端 531 passed、2 skipped，前端 88 passed、Playwright 8 passed；acceptance、boundary、secret、skill 均通过。两个 skip 需要可丢弃 Linux/systemd 主机。
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

- [ ] 推送 `main` 候选并确认 X-ray delivery gates 成功；上一次同提交远端失败原因为固定 jq 下载 HTTP 504，不能复用为通过证据。
- [ ] 创建 annotated `v0.14.5` 标签，手动运行 Release workflow，并回读 Release、标签目标提交及三项资产 SHA-256。

## 外部边界

- [ ] SWAS、Shadowrocket 真机、公网探测、生产镜像切换和生产部署未运行。

## 回退

应用回退使用 `v0.14.4` 或对本阶段相干提交执行 `git revert`。不反向迁移，不恢复已撤销 Token、凭据、安全事件或云操作状态；保留本轮审计和云清理证据。
