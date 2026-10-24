import { expect, test } from '@playwright/test';

const profile = { id: '11111111-1111-4111-8111-111111111111', name: 'browser-fixture',
  status: 'ACTIVE', publishing_frozen: false, expires_at: null, plan_id: null,
  traffic_limit_bytes: null, upload_bytes: 0, download_bytes: 0, usage_updated_at: null, entitlement_state: 'ACTIVE' };
const subscription = { id: '22222222-2222-4222-8222-222222222222', profile_id: profile.id,
  profile_name: profile.name, status: 'ACTIVE', token_epoch: 1, current_revision: null, formats: [], revision_usable: false, policy: profile };

test('creates subscriptions and shows delivery without touching live APIs or browser storage', async ({ page }) => {
  let created = false;
  const writes: string[] = [];
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    let body: unknown;
    if (path === '/api/v1/auth/session') body = { authenticated: true, admin: { username: 'fixture-admin' }, mfa_required: false };
    else if (path === '/api/v1/auth/csrf') body = { csrf_token: 'fixture-csrf' };
    else if (request.method() === 'GET' && path === '/api/v1/subscriptions/') body = { items: created ? [subscription] : [], page: 1, page_size: 25, total: created ? 1 : 0 };
    else if (path === '/api/v1/subscriptions/plans/') body = { items: [], page: 1, page_size: 25, total: 0 };
    else if (path === '/api/v1/subscriptions/catalog/') body = { items: [] };
    else if (request.method() === 'POST' && path === '/api/v1/access-profiles/') {
      expect(request.headers()['idempotency-key']).toMatch(/^[a-f0-9-]{36}$/);
      expect(request.postDataJSON().name).toBe(profile.name);
      writes.push('create'); body = profile;
    } else if (path.endsWith('/subscription/')) {
      writes.push('issue'); created = true;
      body = { subscription_id: subscription.id, token: 'fixture-memory-only', urls: { mihomo: 'https://example.test/s/fixture-only?format=mihomo' }, display_once: true };
    } else if (path.endsWith('/assign/')) {
      expect(request.postDataJSON()).toEqual({ protocol_ids: [] });
      writes.push('assign'); body = { operation_ids: [], pending: false };
    } else throw new Error(`Unexpected test API route ${path}`);
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto('/subscriptions');
  await expect(page.getByRole('heading', { name: '订阅', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '创建订阅', exact: true }).click();
  const editor = page.getByRole('dialog', { name: '创建订阅', exact: true });
  await expect(editor.getByText('暂无可分配协议', { exact: false })).toBeVisible();
  await editor.getByLabel('名称', { exact: true }).fill(profile.name);
  await editor.getByRole('button', { name: '保存订阅', exact: true }).click();
  const delivery = page.getByRole('dialog', { name: '一次性交付', exact: false });
  await expect(delivery.getByText('fixture-memory-only', { exact: true })).toBeVisible();
  await delivery.getByRole('button', { name: '我已安全保存并关闭' }).click();
  await expect(page.getByText('尚未采集', { exact: true })).toBeVisible();
  expect(writes).toEqual(['create', 'issue', 'assign']);
  const browserValues = await page.evaluate(() => JSON.stringify([Object.values(localStorage), Object.values(sessionStorage)]));
  expect(browserValues).not.toContain('fixture-memory-only');
  await expect(page.getByText('fixture-memory-only', { exact: true })).toHaveCount(0);
});

test('opens policy, plan, node protocol and publication history controls', async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown;
    if (path === '/api/v1/auth/session') body = { authenticated: true, admin: { username: 'fixture-admin' }, mfa_required: false };
    else if (path === '/api/v1/subscriptions/') body = { items: [subscription], total: 1, page: 1, page_size: 25 };
    else if (path === '/api/v1/subscriptions/plans/') body = { items: [], total: 0, page: 1, page_size: 25 };
    else if (path === '/api/v1/subscriptions/catalog/') body = { items: [] };
    else if (path === `/api/v1/subscriptions/${subscription.id}/`) body = { ...subscription, profile, assignments: [], revisions: [] };
    else throw new Error('Unexpected fixture request');
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto('/subscriptions');
  await page.getByRole('button', { name: '管理', exact: true }).click();
  const editor = page.getByRole('dialog', { name: '管理订阅' });
  await expect(editor.getByLabel('名称', { exact: true })).toHaveValue(profile.name);
  await editor.getByRole('tab', { name: '套餐管理' }).click();
  await expect(editor.getByRole('button', { name: '新增套餐' })).toBeVisible();
  await editor.getByRole('tab', { name: '节点协议', exact: true }).click();
  await expect(editor.getByRole('button', { name: '登记协议' })).toBeVisible();
  await editor.getByRole('tab', { name: '下发状态与发布历史' }).click();
  await expect(editor.getByText('目标代数', { exact: true })).toBeVisible();
});
