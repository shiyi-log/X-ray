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
代理均使用启动器本次选定的端口；浏览器可使用该端口的 `127.0.0.1` 或
`localhost` 地址打开前端。

启动完成后，终端会打印本次前端和后端地址。可用下面的命令做最小健康检查；
把端口替换为启动器实际打印的值：

```bash
curl --noproxy '*' -i http://127.0.0.1:<后端端口>/health/live
curl --noproxy '*' -i http://127.0.0.1:<后端端口>/health/ready
curl --noproxy '*' -i http://127.0.0.1:<前端端口>/
curl --noproxy '*' -i http://127.0.0.1:<前端端口>/api/v1/auth/session
```

四个请求都应返回 HTTP `200`。`/health/ready` 会同时检查专用 PostgreSQL 和
Redis；前端的 `/api` 请求由 Vite 代理到本次启动器选定的后端端口。若首次启动
需要下载 Compose 镜像，请等待 `postgres` 和 `redis` 都变为 `healthy`；若默认
端口被占用，不要停止占用者，直接使用启动器打印的新地址即可。按 Ctrl+C 只会
停止本次启动器创建的 Django 和 Vite 子进程，专用数据库和 Redis 容器会保留。

开发登录从根目录 `.env` 读取 `XRAY_ADMIN_USERNAME` 和 `XRAY_ADMIN_PASSWORD`；
启动时会在专用 `xray_test` 数据库创建或同步唯一管理员。正常登录流程不要求
首次绑定 TOTP：未绑定时以正确密码进入控制台，已绑定时仍需 TOTP 或一次性
恢复码。生产环境使用相同的可选绑定规则，不读取这组本地开发账号配置。
`XRAY_DISABLE_TOTP=1` 仍只用于隔离测试旁路；验证正常登录和已绑定 MFA 时应
设为 `0`，生产设置始终关闭该旁路。

系统设置提供主动绑定验证器和近期身份验证入口。未绑定时，敏感操作的
step-up 重新验证密码；已绑定时验证密码与 TOTP。普通密码登录不自动获得
近期验证。绑定本身要求已登录并完成近期 step-up，取消或关闭交付页面后应
清除内存中的绑定信息和恢复码，不写入本地存储。

本机密码或 TOTP 恢复使用项目维护命令，并作废原有会话及未消费认证挑战。
本地密码由上述环境账号配置同步；`recover_superadmin` 通过隐藏密码输入确认
管理员身份后清除 TOTP 与恢复码并记录审计。恢复后可直接走正常密码登录，
再由管理员决定是否绑定验证器。不要把密码、验证码或恢复码放进命令参数、
聊天、日志或验收截图。

本地开发配置使用 `XRAY_ENABLE_PROVIDER_NETWORK=1`，允许添加云账号、轮换凭据和
重新验证账号时向 AWS / 阿里云 STS 查询身份。`XRAY_ENV=test` 且未设置该变量时
同样默认允许身份校验联网，其他环境未设置时默认关闭。系统设置中保存的值优先
于环境变量。修改根目录 `.env` 后重新运行
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

启动前先检查端口归属；若端口由其他项目占用，不要停止或复用该服务，应为本项目选择可用的 loopback 端口，并同步更新配置与注册记录。

```bash
cp .env.example .env
make compose-up
make compose-config
```

测试数据库不会使用 SQLite，也不会连接 Shop 的数据库。测试结束后可执行 `make compose-down`；命名卷仅保存本项目测试数据，需要完全重建时再显式删除 `xray-test-postgres` 和 `xray-test-redis`。

### 国内镜像备用

Docker Hub 拉取超时或失败时，可从 DaoCloud 镜像拉取固定版本，再重标记为 Compose 使用的官方镜像名：

```bash
docker pull docker.m.daocloud.io/library/postgres:17.6-alpine
docker image tag docker.m.daocloud.io/library/postgres:17.6-alpine postgres:17.6-alpine
docker pull docker.m.daocloud.io/library/redis:7.4-alpine
docker image tag docker.m.daocloud.io/library/redis:7.4-alpine redis:7.4-alpine
```

前端依赖下载使用 npm 国内镜像 `https://registry.npmmirror.com`。宿主 Node/Vite 配置加载卡住时，可用 Docker Desktop 的 Node 22 隔离环境运行前端；下例只把已排除 `node_modules`、`.env*`、`.git` 和构建产物的源码压入临时容器，不挂载宿主机目录，也不读取根目录 `.env`。Docker Desktop 必须启用主机网络模式（host networking）；该模式已在本项目本机验证，Vite 仍绑定 `127.0.0.1`，API 代理访问本机 loopback 后端。

先在一个终端确认专用 PostgreSQL/Redis 已启动且迁移已完成，然后仅启动本地测试后端。此命令使用 `main.py` 的字面量 `.env` 解析器，配置只进入本机后端进程，不会回显：

```bash
python3 -c 'import os,main; env=main.load_env(main.CONFIG_PATH); env["XRAY_FRONTEND_PORT"]="9528"; env["XRAY_CSRF_TRUSTED_ORIGINS"]="http://127.0.0.1:9528"; python=str(main.ROOT/"backend/.venv/bin/python"); os.execvpe(python,[python,"backend/manage.py","runserver","127.0.0.1:9527","--noreload"],env)'
```

再在第二个终端启动前端隔离环境：

```bash
tar -C frontend --exclude=node_modules --exclude='*/node_modules' --exclude='*/node_modules/*' --exclude='.env*' --exclude='*/.env*' --exclude=.git --exclude='*/.git' --exclude=dist --exclude='*/dist' -cf - . |
docker run --rm -i --pull=missing --network host \
  -e XRAY_BACKEND_PORT=9527 \
  -e XRAY_FRONTEND_PORT=9528 \
  -e COREPACK_NPM_REGISTRY=https://registry.npmmirror.com \
  -e npm_config_registry=https://registry.npmmirror.com \
  docker.m.daocloud.io/library/node:22-bookworm-slim sh -lc 'set -eu
mkdir -p /work/frontend
tar -C /work/frontend -xf -
cd /work/frontend
corepack enable pnpm
corepack prepare pnpm@10.33.0 --activate
pnpm install --frozen-lockfile
pnpm dev'
```

前端服务会监听 `http://127.0.0.1:9528/`，按 Ctrl+C 会移除临时容器。该方式运行的是容器内源码快照，不实时挂载宿主目录；修改前端源码后需停止并重新运行上面的命令。若端口被占用，不要停止占用者；应让后端、CSRF 来源、`XRAY_FRONTEND_PORT` 与 `XRAY_BACKEND_PORT` 使用同一组新端口。

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

前端基于官方 Vben Admin `v5.7.0`（提交
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
