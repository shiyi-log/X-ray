# 第三方代码与许可证

X-ray 项目自有代码的许可证为 `AGPL-3.0-only`，完整文本见
[LICENSE](LICENSE)。该声明不替换第三方代码原有的版权和许可证。

## Vben Admin

- 上游：<https://github.com/vbenjs/vue-vben-admin>
- 固定版本：`v5.7.0`，commit `63a38dce49ba109f61607994e21ba921d8e970e9`。
- 许可证：MIT，完整声明见 [frontend/LICENSE](frontend/LICENSE)。
- Copyright (c) 2024-present, Vben.

`frontend/` 包含 Vben 上游 workspace 源码和 X-ray 应用适配。
上游源码及其版权声明按 MIT 保留；X-ray 自有应用和修改作为本项目的一部分
按 AGPL-3.0-only 提供。上游包范围、适配文件及验证边界见
[frontend/UPSTREAM.md](frontend/UPSTREAM.md)。

## Xray-core

- 上游：<https://github.com/XTLS/Xray-core>
- 当前固定版本：`v26.3.27`。
- 许可证：MPL-2.0。
- 固定源码与下载摘要见 [installer/manifest.json](installer/manifest.json)。

安装器从上游下载固定版本的 Xray-core；它是独立的第三方程序。
本仓库的 AGPL-3.0-only 声明不改变 Xray-core 的 MPL-2.0 许可。
重新分发该程序时应保留其声明并履行其许可证要求。

## 其他依赖

Python 和前端依赖由 [backend/uv.lock](backend/uv.lock) 与
[frontend/pnpm-lock.yaml](frontend/pnpm-lock.yaml) 锁定；其许可证以相应
软件包中的版权和许可证文件为准。操作系统、容器基础镜像、字体和其他
随部署环境分发的组件也保留各自许可。本文记录主要直接复用边界，
不是全部传递依赖的许可证清单；制作分发包时须一并保留适用声明。
