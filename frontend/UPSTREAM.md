# Vben 上游基线

X-ray 的前端以 Vben Admin 的官方源码作为模板进行二次开发。上游基线固定为：

- Repository: `https://github.com/vbenjs/vue-vben-admin`
- Tag: `v5.7.0`
- Commit: `63a38dce49ba109f61607994e21ba921d8e970e9`
- License: MIT；完整许可证文本见 [`LICENSE`](./LICENSE)
- Source verification: 2026-10-18（Asia/Shanghai）；30 个目录、874 个上游文件逐字节复核

## Vendored package closure

仓库内实际 vendored 了该提交的 30 个 workspace package 目录，保留官方源码、
`package.json`、导出和许可证声明。26 个运行时包为：

```text
packages/@core/base/design
packages/@core/base/icons
packages/@core/base/shared
packages/@core/base/typings
packages/@core/composables
packages/@core/preferences
packages/@core/ui-kit/form-ui
packages/@core/ui-kit/layout-ui
packages/@core/ui-kit/menu-ui
packages/@core/ui-kit/popup-ui
packages/@core/ui-kit/shadcn-ui
packages/@core/ui-kit/tabs-ui
packages/effects/access
packages/effects/common-ui
packages/effects/hooks
packages/effects/layouts
packages/effects/plugins
packages/effects/request
packages/constants
packages/icons
packages/locales
packages/preferences
packages/stores
packages/styles
packages/types
packages/utils
```

构建与 workspace 支持包为：

```text
internal/node-utils
internal/tailwind-config
internal/tsconfig
internal/vite-config
```

这些目录来自固定 commit 的源码闭包，不是只保留 Vben 的视觉样式。Vue、路由、
Pinia、Ant Design Vue、Vben layout/preferences/stores、类型、样式、请求和构建
配置均由 workspace 的 `package.json` 与 `pnpm-lock.yaml` 解析；精确依赖版本以
这两个文件为准。

## X-ray adaptation boundary

Vben 包源码中唯一的生产行为适配位于
`packages/stores/src/modules/access.ts`：移除了上游 access store 的持久化配置，
使 access token、refresh token、access code 和 lock-screen 状态只停留在内存中。
`packages/stores/src/modules/access.test.ts` 同时增加了针对持久化插件的回归断言，
确认凭据更新不会读写浏览器存储。X-ray 的授权来源是后端 session Cookie 与 CSRF；
该适配不把密码、令牌或 Cookie 写入 localStorage、sessionStorage 或偏好缓存。

应用层以官方 `web-antd` 模板为基础，使用 `BasicLayout`、`AuthPageLayout`、
`AuthenticationLogin`、VbenForm、preferences 初始化、主题适配、Pinia stores、
i18n 和菜单生成。登录布局、主题、主色、侧边栏尺寸及页面间距采用模板默认值，
不再覆盖为原先的居中登录、固定青色和自定义侧边栏宽度。

十个业务视图使用 Vben `Page` 容器，并以 Ant Design Vue 的 Card、Table、Form、
Input、Select、Button、Modal、Tag、Alert 等组件接入现有接口。原先的自定义
`PageHeader`、应用样式和资源页样式已删除；`packages/ui/src/tokens.css` 不再由
应用加载。业务 API、本地品牌、登录字段、会话守卫和后端 session 合同属于
X-ray overlay，不来自上游演示应用。应用文件包含这些业务适配，不声明与演示
应用逐字节一致。

偏好初始化使用 `xray-manager-v5.7.0-dev` / `xray-manager-v5.7.0-prod` 命名空间，
使恢复后的模板默认值不被旧界面偏好覆盖；不删除旧命名空间或其他浏览器数据。
本地开发直登、TOTP、恢复码、区域默认值、一次性交付和危险操作确认保留现有
业务语义。当前后端没有对应功能的锁屏、通知及演示登录入口保持关闭。

上游 `apps/*` 演示应用、演示路由、Mock server、演示用户、角色管理和 demo 数据
没有被集成；可复用包内仍保留未接入的通用认证/组件源码，以便按需使用，不能据此
推断这些可选功能已经启用。

## External-default boundary

上游包中仍可见若干可选的远程默认值，但当前 X-ray 应用已覆盖或关闭其运行路径：

- Vben 默认头像、Logo 和公司链接被 `apps/web-antd/src/preferences.ts` 覆盖为
  本地 `src/assets/xray-logo.svg`、X-ray 名称和空站点链接。
- Vben 的更新检查被关闭；因此 `CheckUpdates` 不会在本地应用中轮询远程地址。
- 应用使用官方 `@vben/vite-config`；app 配置显式关闭 PWA、import-map、Nitro
  mock 和其他不需要的发布插件，避免加载 PWA 远程图标或 CDN 模块；更新检查则由
  `preferences.app.enableCheckUpdates=false` 关闭。
- 菜单图标直接使用 `lucide-vue-next` 本地组件，不通过 Iconify 远程 provider
  请求图标。

不复制父目录或同级 Shop、`vue-shop-admin`、`shop-xray-installer`、`archive/` 的
源码、别名、环境文件、`node_modules`、API 契约或登录状态；不读取这些边界中的
运行时秘密。
