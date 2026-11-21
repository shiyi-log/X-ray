# 第三方来源与许可证

当前应用源码来自 MHSanaei/3x-ui v3.11.0，提交
`c621ba9014a6aa21fd7c9ecf45655e44e24ebf13`，遵循上游 GNU GPL v3；
根目录 LICENSE 原样保留上游文本，文件内版权声明未删除。来源与原始文件摘要见
UPSTREAM.json 和 artifacts/acceptance/3x-ui-rebase-20261117/replacement-manifest.json。

上游 README 原文保存在 docs/upstream/README.3x-ui.md，其他语言 README 和
CONTRIBUTING.md 按原路径保留。`.github` 中的上游发布/评论/网站工作流、编辑器配置
与上游代理指令没有启用；本项目 README、ignore、CI 和治理文档单独维护。

Go/npm 依赖受各自许可证约束，依赖版本由 go.mod/go.sum 和 frontend/package-lock.json
锁定。Xray-core 采用 MPL-2.0；本次源码导入没有下载或分发 Xray、MTG 或 geo 数据二进制。
发布运行包前还需核对实际打包资产及其许可证。

旧 Django 自有实现、Vben MIT 代码及旧 AGPL-3.0-only 声明仅保留在 Git 历史
`ad90a0f4c5d58adab703ecfe25bf268321f5e44a` 及其祖先提交；它们不再是当前应用构建输入。
历史文档和证据的保留不表示重新许可旧代码，也不表示旧功能已迁移。
