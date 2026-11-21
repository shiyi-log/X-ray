# 3x-ui 底座本地开发

2026-11-17 起，本文件替代旧 Django/Vben 启动方式。固定上游版本、源码摘要和
当前验收结果分别见 ../UPSTREAM.json 与 progress.md 末尾。

## 环境和依赖

需要 Go 1.27.3、Node 26、npm >=11、C 编译器（SQLite CGO）、Python 3。
使用 go.sum 和 frontend/package-lock.json，不运行 pnpm，不复用遗留 frontend/node_modules。
本地遗留目录中的依赖、环境和数据库保留用于历史工作，不是新程序的输入。

在仓库运行 `python3 scripts/export-source.py /tmp/xray-3xui-source.tar`，解压到新的空目录。
构建与测试只针对这个清单导出；可在 Linux 容器中使用该导出作为上下文。
源代码更新后重新导出；现阶段 check-baseline.py 要求上游文件逐字节一致，未来第一次
定制时必须显式记录补丁与上游来源关系，不能默默重写来源摘要来消除检查失败。

## 构建

在干净导出目录中执行：

```bash
HUSKY=0 npm --prefix frontend ci --no-audit --no-fund
npm --prefix frontend run build
go mod download
go mod verify
mkdir -p build
go build -trimpath -o build/x-ui .
```

前端构建输出 internal/web/dist/，Go 将真实页面嵌入程序。`make dist-stub` 仅用于
独立后端测试；占位页面编译不能当作完整应用构建。不要执行上游安装器或直接运行 x-ui。
上游首次启动会打印管理员凭据，需先完成安全的首次配置适配。

## 验证

上游完整前端测试包含 unit、components、Storybook，需先安装 Chromium：

```bash
cd frontend
npx playwright install --with-deps chromium
cd ..
bash scripts/check-local.sh
```

本机上游测试使用随机临时监听，因此放在新建、无 `-p` 端口映射且不使用 host 网络的
隔离容器；依赖和 Chromium 安装完后测试可用 `--network none`。测试临时 SQLite
属于本次测试，不能指向旧数据库。不得通过扩大宿主登记范围绕过本地端口管理。
后续启动宿主服务前，必须检查项目登记、实际监听并经 portctl 受管启动。

check-local.sh 包含来源边界、npm 锁定安装、lint/format/typecheck、完整前端测试、
真实前端构建、Go 依赖验证、完整 Go 测试、vet 和程序编译。CI 执行对应步骤并校验
生成 schema/OpenAPI。上游 make verify 另有 golangci、Storybook 静态构建等门禁，
不能用本地部分通过冒称其全部通过。

Go 默认跳过需要 PostgreSQL、Xray 二进制、master/node 子进程和 scale 开关的测试；
必须在报告中保留 skip。数据库迁移、Xray 数据面、首启管理员、真实浏览器登录、
生产升级和云资源均是后续独立验收，本阶段不执行。

本轮完整测试结果：Go 5572 passed / 67 skipped，前端 215 files / 2018 tests passed。
Go 使用工具链自带 `ZONEINFO=$(go env GOROOT)/lib/time/zoneinfo.zip` 固定时区数据，
避免宿主/容器 tzdata 差异使 America/Havana 的 DST 测试漂移；本机低磁盘测试使用
`-p=1`，临时编译目录以容器 tmpfs 提供并允许执行。完整命令和环境见当前验收回执。

## 回退和版本

当前上游版本从 internal/config/version 编译，根目录旧 VERSION=0.14.12 是历史索引。
本轮没有发布项目版本。源码回退参考 ad90a0f4c5d58adab703ecfe25bf268321f5e44a
与导入清单，保留用户原有未提交文档；不得 hard-reset 或覆盖运行数据库、Token/安全/云历史。
