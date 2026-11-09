# X-ray 管理平台

一个独立、开源、面向单管理员自托管的 X-ray 管理平台。前端基于 Vben Admin 二次开发，后端使用 Django REST Framework；AWS Lightsail 与阿里云轻量应用服务器 SWAS 同时纳入第一版。

本仓库使用自己的超级管理员、PostgreSQL、Redis、密钥、域名、控制服务器及发布流程。Shop 相关仓库仅作只读业务参考，不是本项目的依赖，也不属于本项目改造范围。

管理员 TOTP 为可选绑定：未绑定时使用正确密码登录，已绑定时继续验证 TOTP
或一次性恢复码。系统设置提供主动绑定与近期身份验证入口；敏感操作仍须
step-up，未绑定时重新验证密码，已绑定时验证密码与 TOTP。登录状态由服务端
会话管理，CSRF、会话撤销和目标确认保持生效。

## 当前状态

2026-11-10：当前交付候选版本为 `0.14.5`。本版完善地址池调度重试、删除后资源账本状态、订阅节点数量核对和撤销 Token 的失效发布处理，并补齐 outbox Celery app 绑定与订阅路径日志脱敏。两台授权范围内 Lightsail 节点完成池补齐、按 `(created_at, pk)` 选取一台每日 stop/start、动态 IPv4/健康/IP 刷新、订阅签发/发布/撤回、节点计数和流量统计验收；池从 `2→1` 的自动缩容成功。池降至 0 后，第二台实例已由 provider 确认缺失且配额释放，但当时的删除 Operation 因已撤销 Token 仍尝试重新发布而为 `PARTIALLY_SUCCEEDED`；候选代码现仅在撤销时间、墓碑和无活动 Token 均验证时跳过重发，并通过本地回归，未重跑真实 AWS。清理读回比授权截止晚约三分钟，实例级最终账单未知，profile 级撤回正向控制仍未通过；完整边界以 `VERSION`、`docs/progress.md` 与 `tests/acceptance/matrix.json` 为准。

本轮两台授权 AWS Lightsail 测试节点均已清理并读回不存在，通过认证 SSH/Xray 采集流量；尚未执行 SWAS、独立 SSH 登录或 Google 公网探测、Shadowrocket 真机、独立生产服务器、域名/TLS 或生产部署。候选提交 `e38b48b` 的远端 delivery gates 已通过，annotated `v0.14.5` 标签已推送并指向该提交；正式 Release workflow 仍待手动运行。AWS 总体验收仍有独立阻断，本地 Compose、Fake/Stub、镜像、恢复演练、提交与标签都不代表生产部署。

- [正式设计规格](docs/superpowers/specs/2026-09-16-xray-manager-design.md)
- [开发计划总览](docs/superpowers/plans/2026-09-16-xray-manager.md)

## 目录约定

```text
backend/       Django API、领域模型、云适配器、Celery
frontend/      新项目自有的 Vben 应用及必要的工作区包
installer/     新项目自有安装、配置、验证与凭据撤销工具
deploy/        Compose、Nginx、备份和发布配置
docs/          规格、分阶段计划、接口与运维文档
tests/         跨服务契约和端到端测试
archive/       本机参考归档，禁止提交、构建、发布或运行时引用
```

前端固定参考 Vben `v5.7.0` / `63a38dce49ba109f61607994e21ba921d8e970e9`，精确来源、许可证和保留包见 `frontend/UPSTREAM.md`。原先遗留的根目录 `nodes/`、`xray_service/`、`static/` 仅是空骨架，不视为可运行系统。

## 执行边界

本地与 CI 使用专用测试数据库及模拟云适配器。真实云验收需要另行确认测试账号、区域、套餐和预算；资源删除与 IP 释放单独授权。GitHub 源码发布和安装器资产使用不可变版本标签；生产服务器仍需按 `docs/release.md` 使用不可变镜像摘要执行发布，GitHub Release 不等于生产部署。

`archive/` 包含此前按用户要求保存的完整 Shop 快照，可能含敏感信息。它仅保存在本机，父目录权限为 `0700`，不得加入 Git 或任何构建上下文。新服务从空数据库、新密钥和新管理员开始。

## 开源许可证

Copyright (c) 2026 shiyi-log and X-ray contributors.

本项目自有代码采用 **GNU Affero General Public License v3.0 only**
（SPDX：`AGPL-3.0-only`），完整条款见 [LICENSE](LICENSE)。
源码仓库：[shiyi-log/X-ray](https://github.com/shiyi-log/X-ray)。

允许使用、修改、分发和商业使用；分发，以及通过网络向用户提供修改后的程序时，
需要遵守 AGPL-3.0 对相应源码提供、许可证和版权声明等方面的要求。网络交互的
源码提供义务见许可证第 13 条。自托管修改版本时，请向远程交互用户提供获取
该运行版本相应源码的方式。

Vben 上游代码保留其 MIT 许可证及版权声明；Xray-core 使用 MPL-2.0，
其他第三方依赖按各自许可证使用。来源和适用边界见
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和
[frontend/UPSTREAM.md](frontend/UPSTREAM.md)。仓库开源不代表生产部署或真实云验收完成，
当前能力与限制仍以本页当前状态和验收记录为准。
