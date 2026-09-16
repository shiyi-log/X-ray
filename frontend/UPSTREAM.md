# Vben 上游基线

- Repository: `https://github.com/vbenjs/vue-vben-admin`
- Tag: `v5.7.0`
- Commit: `63a38dce49ba109f61607994e21ba921d8e970e9`
- License: MIT，完整文本见 `LICENSE`
- Verified: 2026-09-17

本目录按该提交的 `apps/web-antd`、Vue Router、Pinia、Ant Design Vue 与 Vite
拓扑建立独立的最小 workspace。业务代码为 X-ray 管理平台专用实现；未复制演示
路由、Mock server、演示用户、角色管理或其他产品工作区。

保留的运行包：Vue、Vue Router、Pinia、Ant Design Vue、Lucide Vue。
保留的构建/验证包：Vite、TypeScript、Vue TSC、Vitest、Vue Test Utils、
Playwright、ESLint、OpenAPI TypeScript。精确版本以 `package.json` 和
`pnpm-lock.yaml` 为准。

本 workspace 不引用父目录或同级 Shop/Vben 项目的源码、别名、环境文件、
`node_modules`、API 契约或登录状态。
