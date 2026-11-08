# X-ray 管理平台

一个独立、开源、面向单管理员自托管的 X-ray 管理平台。前端基于 Vben Admin 二次开发，后端使用 Django REST Framework；AWS Lightsail 与阿里云轻量应用服务器 SWAS 同时纳入第一版。

本仓库使用自己的超级管理员、PostgreSQL、Redis、密钥、域名、控制服务器及发布流程。Shop 相关仓库仅作只读业务参考，不是本项目的依赖，也不属于本项目改造范围。

## 当前状态

2026-11-07：当前交付候选版本为 `0.14.3`。本版补齐固定 Shadowsocks/TCP/AES-128-GCM profile 凭据撤回运行时校验、旧连接关闭与配置 generation/hash 读回，并以 lease fencing 阻止过期 worker 写入成功状态。v0.14.0 起的地区地址池定时对齐、每日单台轮转重启、重启后 IP/健康/订阅对账、状态/IP/流量同步和节点数量核对，以及后续订阅部分发布重试、SOCKS5 流量计量继续保留。真实 AWS bootstrap 尚未验收；自动创建仍可能停在 `PROVISIONED`/`NEEDS_RECONCILIATION`，实际云、SSH、动态 IP、设备订阅和生产验收继续以 `VERSION`、`docs/progress.md` 与 `tests/acceptance/matrix.json` 的证据为准。

真实 AWS/SWAS、远程 SSH、Google 公网探测、Shadowrocket 真机、独立生产服务器、域名/TLS、实例删除、静态 IP 释放和生产发布没有执行。本地 Compose、Fake/Stub、镜像、恢复演练、提交与标签都不代表生产上线。

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
