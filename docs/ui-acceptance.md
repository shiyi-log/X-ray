# P5 控制台浏览器验收

## 验收环境

- 日期：2026-09-17
- 应用版本：`0.5.0`
- 浏览器：本机 Google Chrome，由 Playwright `channel=chrome` 驱动
- 桌面视口：`1440x900`
- 移动视口：`390x844`
- 后端：真实 Django 请求路径、专用 PostgreSQL `xray_test`、专用 Redis
- 云与节点执行：仅测试 Fake/固定记录；未执行真实云、SSH 或公网探测

测试数据由 `seed_e2e --reset` 生成。该命令只允许在 `XRAY_ENV=test` 且数据库名
严格为 `xray_test` 时运行。认证使用真实密码、TOTP、Cookie、CSRF 和 session API；
前端没有拦截或伪造 API 响应。

## 通过项

| 项目 | 证据 | 状态 |
|---|---|---|
| 密码与 TOTP 登录 | `frontend/tests/e2e/auth.setup.ts` | passed |
| 刷新恢复服务器会话 | `frontend/tests/e2e/resources.spec.ts` | passed |
| 真实空状态 | `artifacts/acceptance/0.5.0/screenshots/desktop-operation.png` 同次流程 | passed |
| API 断网失败状态 | `frontend/tests/e2e/resources.spec.ts` | passed |
| 一次性交付关闭即清除 | `artifacts/acceptance/0.5.0/screenshots/desktop-access-profiles.png`（关闭后） | passed |
| 危险确认与部分撤销 | `artifacts/acceptance/0.5.0/screenshots/desktop-partial-revocation.png` | passed |
| 移动端布局与无页面级横向溢出 | `artifacts/acceptance/0.5.0/screenshots/mobile-subscriptions.png` | passed |
| 脱敏交互 trace | `artifacts/acceptance/0.5.0/resource-flow-sanitized.zip` | passed |

Trace 只覆盖不含秘密的空状态和 Operation 恢复流程，并在写入验收目录后删除
Playwright 的网络归档；因此不包含 Cookie、CSRF、密码、TOTP 或订阅 Token。
一次性交付场景不保存 trace，截图在秘密对话框关闭且 DOM 清空后才生成。

## 视觉结论

桌面管理壳、表格、Operation 时间线和撤销结果没有重叠或文本截断。移动端导航
使用抽屉，订阅记录改为逐字段布局，格式与危险操作按钮无需横向滚动即可读取。
按钮、固定宽度状态和 UUID 在 `390px` 视口内保持可操作。

当前会话没有可用的内置图像概念生成工具；遵循图像技能限制，未切换到需要额外
API Key 的 CLI。视觉验收以真实浏览器 DOM、桌面/移动截图和溢出断言完成。

## 外部边界

真实 AWS Lightsail、阿里云 SWAS、远程 SSH、Google 公网探测、独立生产服务器与
真实删除/IP 释放均没有授权证据，本阶段保持 `blocked` 或 `risky_not_executed`。
