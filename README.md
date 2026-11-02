# X-ray 管理平台

一个全新、独立的私有 X-ray 管理产品。前端基于 Vben Admin 二次开发，后端使用 Django REST Framework；AWS Lightsail 与阿里云轻量应用服务器 SWAS 同时纳入第一版。

本仓库使用自己的超级管理员、PostgreSQL、Redis、密钥、域名、控制服务器及发布流程。Shop 相关仓库仅作只读业务参考，不是本项目的依赖，也不属于本项目改造范围。

## 当前状态

2026-11-02：当前交付版本为 `0.12.0`。本版增加可在系统设置中启停并配置重复时间的服务器状态同步，扩展 AWS Lightsail 地区目录并用中文显示，修正操作中心、审计日志和订阅状态展示；节点刷新仍只读云端状态，云端不存在与读取失败保持可区分。实际云、SSH、生产和设备验收继续以 `VERSION`、`docs/progress.md` 与 `tests/acceptance/matrix.json` 的证据为准。

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
