# P5 Vben 独立控制台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在独立 Vben 前端交付安全登录和全部管理页面，与真实本地后端契约对接。

**Architecture:** 固定 Vben 5.7 基线和自有 workspace 包，OpenAPI 生成类型；服务器 session/CSRF 驱动请求层，Operation 轮询驱动进度。

**Tech Stack:** Node 22 LTS（≥22.18）、pnpm 10.33.0、Vue 3、Vben 5.7、Ant Design Vue、Pinia、Vue Router、Vitest、Playwright。

**Spec:** [设计规格](../specs/2026-09-16-xray-manager-design.md)，章节 3、5、10。

## Global Constraints

- 前端位于同仓 frontend/，不引用 vue-shop-admin 路径、环境或登录契约；保留上游许可。
- 唯一管理员，无普通用户/角色页面；长期登录凭据不进 localStorage。
- API 失败显示错误，空数据是真实空状态；危险动作后端和前端都验证。
- 完整行为等后端 OpenAPI 固定后开发；规格的全局边界均适用。

---

### Task P5.1: Vben 基线、会话/CSRF 与登录

**Files:**
- Create: `frontend/package.json`、`pnpm-lock.yaml`、`pnpm-workspace.yaml`、`apps/web-antd/`、`packages/`（最小必要包）、`LICENSE`、`UPSTREAM.md`。
- Create: `frontend/apps/web-antd/src/api/{request,auth}.ts`、`src/stores/session.ts`、`src/router/guards.ts`、`src/views/auth/{login,totp,recovery}.vue`。
- Test: `frontend/apps/web-antd/src/api/request.test.ts`、`src/views/auth/auth.test.ts`。
- Modify: `README.md`、`docs/development.md`。

**Interfaces:**
- Consumes: P1 auth API。
- Produces: `apiRequest<T>(path:string,init?:RequestInit):Promise<T>`；`loadSession():Promise<AdminSession>`；`clearSensitiveState():void`；`AdminSession` 由 P1 OpenAPI 生成。
- 根 scripts 统一 `pnpm --dir frontend test:unit`、`typecheck`、`lint`、`build`；应用名称 `@xray/web-antd`。

- [ ] **Step 1: 从官方固定提交建立最小 Vben workspace，记录具体 tag/commit、license、包清单。** 不允许把“Vben 5.7 系列”作为浮动依赖；`UPSTREAM.md` 明示精确基线，不复制 Shop 的前端工作区。去除仅有样例用途的路由、Mock server、演示用户和用户管理入口，保留 Vben 核心壳。
- [ ] **Step 2: 写失败请求/认证测试。**

```ts
it('写请求携带 cookie 与 CSRF，密码阶段不会获得管理会话', async () => {
  const calls: RequestInit[] = [];
  vi.stubGlobal('fetch', vi.fn(async (_url, init) => {
    calls.push(init);
    return new Response(JSON.stringify({ mfa_required: true, authenticated: false }));
  }));
  await apiRequest('/api/v1/auth/login', { method: 'POST', body: '{}' });
  expect(calls[0]?.credentials).toBe('same-origin');
  expect(new Headers(calls[0]?.headers).get('X-CSRFToken')).toBeTruthy();
  expect(localStorage.getItem('accessToken')).toBeNull();
});
```

测试前 fixture 为 `/auth/csrf` 提供测试 token；另测 401 清敏感状态、恢复码路径、首次 TOTP setup、CSRF失败不得自动无限重试。
- [ ] **Step 3: 运行失败测试 `pnpm --dir frontend test:unit -- request.test.ts auth.test.ts`。**
- [ ] **Step 4: 实现独立请求客户端、路由守卫和两阶段登录。**

```ts
const response = await fetch(path, {
  ...init,
  credentials: 'same-origin',
  headers: { ...Object.fromEntries(new Headers(init.headers)), 'X-CSRFToken': csrfToken },
});
if (response.status === 401) {
  clearSensitiveState();
  throw new Error('会话已过期，请重新登录');
}
```

CSRF 由 P1 endpoint 提供并缓存内存；恢复后重新取。登录态只来自 session API；401 退出，403 区分 MFA/step-up/CSRF 不都当登录失败。Cookie 由服务器控制。
- [ ] **Step 5: 测试、typecheck、lint、build 通过，提交 `feat: bootstrap independent vben console authentication`。** 保留许可证且不提交 node_modules/dist。

### Task P5.2: OpenAPI、资源页面和持久化操作中心

**Files:**
- Create: `backend/apps/{cloud_accounts,nodes,operations,subscriptions,audit}/{views,serializers,urls}.py`（各应用按 P1-P4 模型实现）。
- Create: `backend/openapi/schema.yaml`、`frontend/apps/web-antd/src/api/generated/schema.ts`、`frontend/scripts/generate-api.mjs`。
- Create: `frontend/apps/web-antd/src/views/{overview,cloud-accounts,node-pools,nodes,operations,audit,system}/index.vue`、`src/composables/useOperation.ts`。
- Test: `backend/tests/test_admin_contract.py`、`frontend/apps/web-antd/src/composables/useOperation.test.ts`、`tests/e2e/resources.spec.ts`。

**Interfaces:**
- Consumes: P1 auth、P2 account/provider、P3 Operation、P4 subscription services；views 只调用服务，不在请求里跑 SSH/云写。
- Produces: OpenAPI 固定 operationId；列表统一 `{items,total,page,page_size}`；Operation 包含 status/current_step/steps/can_cancel/error/updated_at。
- `useOperation(operationId:string)` 返回 data/error/reload/stopPolling；组件卸载停止轮询，重新挂载按 ID 恢复。

- [ ] **Step 1: 写 API 契约和刷新恢复失败测试。**

```ts
test('刷新后从服务器恢复同一个 operation', async ({ page }) => {
  await page.goto('/operations/11111111-1111-4111-8111-111111111111');
  await expect(page.getByTestId('operation-state')).toHaveText('运行中');
  await page.reload();
  await expect(page.getByTestId('operation-id')).toHaveText('11111111-1111-4111-8111-111111111111');
});
```

E2E 此固定 ID 来自本任务的 Fake-backend seed，auth fixture 从 P5.1 的真实认证路径登录；API 断连时断言显示错误且不出现假进度。列表空数据、双云 raw status、cost currency/time、capability unsupported/unverified 都覆盖。
- [ ] **Step 2: 先运行 `uv run --project backend pytest -c backend/pyproject.toml backend/tests/test_admin_contract.py -q` 和上述页面测试确认失败。**
- [ ] **Step 3: 实现资源 API 与生成工具，再实现页面。**

```python
operation = operation_service.submit(
    kind=payload['kind'], target_id=node.pk, params=payload['params'],
    key=request.headers['Idempotency-Key'], preview_id=payload.get('preview_id'))
return Response({'operation_id': str(operation.pk), 'status': operation.status,
                 'target_type': 'node', 'target_id': str(node.pk)}, status=202,
                headers={'Location': f'/api/v1/operations/{operation.pk}'})
```

生成命令 `uv run --project backend python backend/manage.py spectacular --file backend/openapi/schema.yaml --validate` 与 `pnpm --dir frontend generate:api`；node 脚本只读 schema 并调用锁定版本的类型生成器。页面选择值用 capability 控制，错误保留 retryable/code/request ID，无原始异常。
- [ ] **Step 4: 运行契约测试、前端单测/类型/build 与真实本地后端 E2E。** 同次生成两次结果无差异，CI 用 `git diff --exit-code -- backend/openapi frontend/apps/web-antd/src/api/generated` 检查生成物。
- [ ] **Step 5: 提交 `feat: connect vben resource management and operation tracking`。**

### Task P5.3: 撤销 UI、危险确认与安全系统设置

**Files:**
- Create: `frontend/apps/web-antd/src/components/DangerConfirm.vue`、`src/components/SecretDelivery.vue`、`src/views/{access-profiles,subscriptions}/index.vue`。
- Modify: `frontend/apps/web-antd/src/views/{nodes,cloud-accounts,system}/index.vue`。
- Test: `frontend/apps/web-antd/src/components/DangerConfirm.test.ts`、`tests/e2e/{revocation,danger-actions}.spec.ts`。
- Create: `docs/ui-acceptance.md`。

**Interfaces:**
- Consumes: ActionPreviewService、P4 发布/令牌/撤销 API。
- `DangerConfirm` props `preview,requiredPhrase`，emit `confirm({preview_id,confirmation,idempotency_key})`；近期认证不足弹出 step-up。
- `SecretDelivery` 只读当前交付内存，关闭/5分钟/退出即清除；不在 URL、localStorage、错误报告或分析事件存秘密。

- [ ] **Step 1: 写最关键失败用例。**

```ts
test('链接撤销完成但节点隔离未确认不能显示撤销成功', async ({ page }) => {
  await page.goto('/subscriptions');
  await page.getByRole('button', { name: '强制撤销访问' }).click();
  await page.getByLabel('确认文本').fill('确认强制撤销');
  await page.getByRole('button', { name: '提交操作' }).click();
  await expect(page.getByText('链接已撤销')).toBeVisible();
  await expect(page.getByText('节点访问撤销未确认')).toBeVisible();
  await expect(page.getByText('全部旧凭据已失效', { exact: true })).toHaveCount(0);
});
```

Fake seed 返回 P4 的 partial result；另测共享密钥影响列表、令牌只显示一次、复制不生成新版本、过期 preview 返回409、取消不能复活令牌。
- [ ] **Step 2: 运行组件和 E2E 失败测试。**
- [ ] **Step 3: 实现危险确认绑定与诚实进度。**

```ts
const canSubmit = computed(() =>
  typedPhrase.value === props.requiredPhrase &&
  Date.now() < Date.parse(props.preview.expires_at) && !submitting.value,
);
```

后端独立重查 preview、target generation、auth step-up；409 后必须刷新预览和重新确认。共享协议文案注明其他有效设备需重新导入新凭据；云删除、IP释放分别操作。管理域名/allowlist 第一版页面只读，由部署配置修改，Django 不写 Nginx 文件。
- [ ] **Step 4: 在实际浏览器完成全流程并保存脱敏截图/断言。** 登录→假云账号→节点池→模拟建机→安装→发布→撤销→隔离失败→恢复；同时检查桌面布局与窄屏关键操作。
- [ ] **Step 5: 前端所有门禁和 API 回归通过，提交 `feat: add safe subscription revocation controls`。**

## P5 完成门禁

- [ ] 新 Vben 可独立安装/build，没有跨仓库 alias，菜单只包含已实现页面。
- [ ] P1–P4 API 在真实本地后端+模拟云条件下可完整操作，浏览器证据不是静态页面截图代替。
- [ ] Token 生命周期、危险动作预览、未确认撤销、共享密钥影响、会话过期都有实际交互测试。
