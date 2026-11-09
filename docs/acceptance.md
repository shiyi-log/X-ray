# 验收边界与证据规则

本项目把代码交付、真实云验收和生产上线分开判定。任何本地测试、Fake/Stub、
Compose、镜像构建、提交或标签都不能替代真实云或生产证据。

## 状态词

`tests/acceptance/matrix.json` 只允许以下状态：

- `passed`：本项范围内的命令退出码为 0，且存在可复核证据。
- `failed`：已执行，结果不满足验收要求；必须保留脱敏失败证据。
- `blocked`：缺少授权、账号、预算、服务器、域名或其他外部前置条件。
- `not-run`：未执行且不涉及高风险副作用。
- `risky_not_executed`：因删除实例、释放 IP、生产切换等风险而未执行。

`scripts/validate-acceptance.py` 强制校验状态、版本、唯一 ID、`passed` 证据和完整
提交 SHA。真实云 `passed` 还必须有结构化授权引用、Operation UUID、provider
request ID、脱敏资源引用、带时区时间、区域和探测结果。生产 `passed` 必须有
脱敏服务器引用、TLS 证据、backend/frontend/backup-tools 不可变镜像摘要和真实
恢复证据。Fake、Mock 或 Stub 不能写成真实云通过。

## 本地门禁

从仓库根目录运行：

```bash
./scripts/check-local.sh
```

脚本按固定顺序验证运行时、专用 PostgreSQL/Redis、生产/预发布 Compose、三个
本地镜像、Django 与迁移、Ruff、完整 pytest、OpenAPI 双生成、固定 Xray、四种
订阅格式、前端 typecheck/lint/unit/build、真实浏览器 E2E、ShellCheck、边界、
Gitleaks、项目技能和验收矩阵。每一门的日志及退出码写入：

```text
artifacts/acceptance/<version>/gates/
```

`./scripts/check-local.sh --list` 只列出门禁，不执行。工具缺失、版本不符或动态
镜像测试跳过都不能记为 `passed`。固定 Xray 门禁必须设置
`XRAY_REQUIRE_FIXED_BINARY=1`，并只使用 `installer/manifest.json` 固定的
v26.3.27 资产和 SHA-256。

## 证据卫生

可提交或上传的证据仅包括脱敏日志、JUnit、Playwright 截图/已移除网络归档的
trace、镜像摘要、备份 manifest 和恢复 receipt。禁止保存环境文件、数据库
dump、Cookie、原始订阅 Token、TOTP、私钥、云凭据和包含请求正文的 trace。

CI 使用测试专用 `xray_test` PostgreSQL 与 Redis、固定依赖和 Fake/Stub provider；
工作流没有真实云、SSH、Google 公网探测、删除实例或释放 IP 的入口。

## 当前外部限制

截至 2026-11-10，两台本轮授权 AWS Lightsail 测试节点已清理并由 provider 读回不存在；
地址池、每日轮转重启、动态 IPv4、健康、订阅发布/撤回、节点计数和流量统计有范围内证据。
完整 AWS 验收仍因 profile 级撤回正向控制未通过、旧删除 Operation 部分成功且修复未在 AWS
重跑、逐资源最终账单未知而保持 `blocked`。SWAS、独立 SSH 登录、Google 公网探测、
Shadowrocket 真机、独立生产服务器、域名/TLS 与生产部署没有运行；对应矩阵项继续保持
`blocked`、`not-run` 或 `risky_not_executed`，不得由 GitHub Release 或本地/CI 结果替代。
