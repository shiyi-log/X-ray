# 本地开发

## 一键启动

完成下方依赖安装和根目录 `.env` 配置、启动 Docker Desktop 或 Colima、
首次执行数据库迁移后，在项目根目录运行：

```bash
python3 main.py
```

也可以在 PyCharm 中直接运行根目录 `main.py`。启动器自动加载根目录
`.env`，启动项目专用 Compose 依赖，检查数据库迁移状态，然后启动
Django 和 Vite。默认后端端口为 `9527`、前端端口为 `9528`；端口冲突时
启动器会保留已有服务，并自动选择其他可用 loopback 端口。终端会显示本次
实际地址。按 Ctrl+C 或停止运行
会终止本次启动的两个服务；数据库和 Redis 容器保留，方便再次启动。
启动器只支持本地 `config.settings.test` / `XRAY_ENV=test`，不会停止或复用
已有服务。依赖缺失或有待执行迁移时会提示退出。CSRF 信任来源和前端 API
代理均使用启动器本次选定的端口。
开发登录从根目录 `.env` 读取 `XRAY_ADMIN_USERNAME` 和 `XRAY_ADMIN_PASSWORD`；
启动时会在专用 `xray_test` 数据库创建或同步唯一管理员。`XRAY_DISABLE_TOTP=1`
只对本地测试设置生效，因此开发阶段输入用户名和密码即可进入控制台。
生产设置始终要求 MFA，不读取这组本地开发账号配置。

本地开发配置使用 `XRAY_ENABLE_PROVIDER_NETWORK=1`，允许添加云账号、轮换凭据和
重新验证账号时向 AWS / 阿里云 STS 查询身份。修改根目录 `.env` 后重新运行
`main.py` 生效。需要主动关闭在线身份校验时可以设为 `0`；创建、停止、删除
云资源仍通过各自的操作授权流程执行。本地自动化测试继续使用 Mock/Stub，
无需真实云凭据或网络请求。

首次配置后执行迁移（配置值不会回显）：

```bash
set -a
source .env
set +a
uv run --project backend python backend/manage.py migrate --noinput
```

## 隔离依赖

P1 使用独立 PostgreSQL 17 和 Redis 7.4，Compose 项目名固定为 `xray-test`。宿主机端口只绑定 loopback：

| 服务 | 容器端口 | 宿主机端口 | 数据库/实例 |
| --- | ---: | ---: | --- |
| PostgreSQL | 5432 | 55432 | `xray_test` |
| Redis | 6379 | 56379 | DB `0` |

端口已在本机检查无监听，不应停止其他项目来抢占端口。若端口发生冲突，先重新执行端口检查并更新本项目配置与注册记录。

```bash
cp .env.example .env
make compose-up
make compose-config
```

测试数据库不会使用 SQLite，也不会连接 Shop 的数据库。测试结束后可执行 `make compose-down`；命名卷仅保存本项目测试数据，需要完全重建时再显式删除 `xray-test-postgres` 和 `xray-test-redis`。

## 本地门禁

```bash
make check-boundary
make secret-scan
uv run --project backend python backend/manage.py check --settings=config.settings.test
uv run --project backend pytest -c backend/pyproject.toml backend/tests -q
```

真实 AWS、阿里云、SSH、Google 探测、服务器部署和生产密钥不属于本地测试流程；测试中的云和 SSH 必须使用 stub/fake。

## 前端

前端是仓库内独立 pnpm workspace，要求 Node.js `>=22.18` 和 pnpm `10.33.x`，不读取同级项目的依赖或环境文件。

前端基于官方 Vben Admin `v5.7.0`（commit
`63a38dce49ba109f61607994e21ba921d8e970e9`，MIT）源码闭包二次开发。实际源码已
vendored 为 30 个 workspace 包（26 个运行包和 4 个内部构建支持包），清单、
许可证、同步边界和唯一 access-store 持久化适配见
[`frontend/UPSTREAM.md`](../frontend/UPSTREAM.md)。应用恢复官方 `web-antd` 模板的
布局、主题、主色、侧边栏尺寸和页面间距，使用 BasicLayout、AuthPageLayout、
AuthenticationLogin、VbenForm、preferences、主题适配、Pinia stores、i18n 和菜单
生成。十个业务视图均以 Vben Page 配合 Ant Design Vue 组件开发；原先自写的
PageHeader、应用及资源页 CSS 已移除，X-ray token 样式不再加载。

X-ray 仅在这些模板组件上接入品牌、登录会话、业务路由和现有 API。偏好命名空间
改为 `xray-manager-v5.7.0-dev` / `xray-manager-v5.7.0-prod`，使旧偏好不覆盖模板
默认值；原有浏览器数据不删除。本地密码直登和原有 MFA 流程保持可用。上游演示
路由、Mock server、演示用户、角色管理和 demo 数据没有接入。

Vben 默认远程头像、Logo 和公司链接已由本地 X-ray 偏好设置覆盖，更新检查已关闭。
当前 app 使用官方 `@vben/vite-config`，并显式关闭 PWA、import-map、Nitro mock
和其他不需要的发布插件。业务菜单图标使用本地 `lucide-vue-next` 组件，不经
Iconify provider 发起外部请求。

```bash
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend typecheck
pnpm --dir frontend lint
pnpm --dir frontend test:unit
pnpm --dir frontend build
pnpm --dir frontend dev
```

直接运行 `pnpm --dir frontend dev` 时默认监听 `127.0.0.1:9528`，并把 `/api` 与 `/s` 代理到 `127.0.0.1:9527`。根目录 `main.py` 一键启动会自动选择端口，并将选定值同步到代理。登录状态只来自服务器 session Cookie；CSRF token、MFA challenge、首次绑定密钥和恢复码只保存在当前页面内存。
