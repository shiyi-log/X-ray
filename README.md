# X-ray · 基于 3x-ui 的二次开发

本项目已按 2026-11-17 的决定放弃原 Django/Vben 实现，改为基于
[MHSanaei/3x-ui](https://github.com/MHSanaei/3x-ui) 二次开发。第一阶段只建立
可追溯的上游底座和本地构建、测试流程；云节点、订阅池、自动化与在线升级等旧定制功能
不属于当前实现，后续按独立需求逐项重做。

## 固定基线

- 上游版本：`v3.11.0`
- 上游提交：`c621ba9014a6aa21fd7c9ecf45655e44e24ebf13`
- Go `1.27.3`，Node `26`，npm `>=11`；依赖使用原始 `go.sum` 和 `frontend/package-lock.json`。
- Go/Gin/GORM 后端，React 19 / Ant Design 6 / TypeScript 前端；SQLite/PostgreSQL 由上游支持。
- 来源、归档摘要及回退点见 [UPSTREAM.json](UPSTREAM.json)，逐文件 SHA256 见
  [导入清单](artifacts/acceptance/3x-ui-rebase-20261117/replacement-manifest.json)。

## 开发入口

先读 [本地开发说明](docs/development.md)。使用干净源码副本执行构建，避免复用遗留依赖：

```bash
python3 scripts/check-baseline.py
python3 scripts/export-source.py /tmp/xray-3xui-source.tar
```

导出目标必须尚不存在。导出只包含清单中的公开源码和构建门禁，不读取本机 `.env`、
数据库、旧 `node_modules`、证据或 Git 凭据。完整验证入口为 `scripts/check-local.sh`；
会监听临时端口的测试应在无宿主端口映射的隔离容器执行。

当前目录结构：

```text
main.go           3x-ui 主程序
internal/         管理服务、数据库、订阅、节点及 Xray 适配
frontend/         React 应用及上游前端测试
tools/            上游代码生成工具
scripts/          上游工具及本项目来源/构建验证入口
UPSTREAM.json     上游不可变版本锁定
```

上游安装器、Dockerfile 和系统服务文件作为底座源码保留，尚未完成本项目部署适配。
首次启动的管理员凭据交付和 Xray/MTG/geo 资产锁定仍需后续处理；本阶段不自动运行安装器
或启动面板。构建成功仅证明程序可编译，不代表代理连通或生产可用。

## 验证与历史

本阶段实际验证结果见 [进度](docs/progress.md) 末尾与
[底座验收目录](artifacts/acceptance/3x-ui-rebase-20261117/)。新 CI 仅执行源码门禁，
不发布或部署。没有创建新的项目版本、提交或标签。

应用代码保持上游原样；本地 `.env.example` 关闭调试模式，且移除了只验证上游
自动评论机器人的测试文件。具体差异与原始摘要均记入来源清单。

旧代码保留在 Git 历史 `ad90a0f4c5d58adab703ecfe25bf268321f5e44a`；
旧 `VERSION`、`CHANGELOG.md`、`docs/version-record.md` 与 `tests/acceptance/matrix.json`
只记录旧系统，不能用于判定当前 3x-ui 底座的能力或版本。旧 `docs/`、`artifacts/`、
`output/` 的历史证据以及已有本地数据和环境保留，但不参与新构建。

## 许可证

当前 3x-ui 底座遵循上游 GNU GPL v3，原文见 [LICENSE](LICENSE)。
上游版权和第三方许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
旧项目自有代码的 AGPL 声明保留在 Git 历史，不能用它替换上游代码的许可证。
