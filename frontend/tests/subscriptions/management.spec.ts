import { expect, test } from '@playwright/test';

const profile = { id: '11111111-1111-4111-8111-111111111111', name: 'browser-fixture',
  status: 'ACTIVE', publishing_frozen: false, expires_at: null, plan_id: null,
  traffic_limit_bytes: null, upload_bytes: 0, download_bytes: 0, usage_updated_at: null, entitlement_state: 'ACTIVE' };
const subscription = { id: '22222222-2222-4222-8222-222222222222', profile_id: profile.id,
  pool_id: '33333333-3333-4333-8333-333333333333', pool_name: 'default', profile_name: profile.name,
  status: 'ACTIVE', current_token_status: 'ACTIVE', token_epoch: 1, current_revision: null, formats: [], revision_usable: false, policy: profile };

test('creates and revokes a subscription link without storing its one-time token', async ({ page }) => {
  let created = false;
  let revoked = false;
  const writes: string[] = [];
  const token = {
    id: '44444444-4444-4444-8444-444444444444',
    subscription_id: subscription.id,
    token_epoch: 1,
    status: 'ACTIVE',
    created_at: '2026-11-06T08:00:00Z',
    revoked_at: null,
    is_current: true,
  };
  const preview = {
    id: '55555555-5555-4555-8555-555555555555',
    kind: 'subscription.token_revoke',
    target_id: token.id,
    required_phrase: '确认撤销令牌',
    expires_at: new Date(Date.now() + 300_000).toISOString(),
    snapshot: {},
  };
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    let body: unknown;
    if (path === '/api/v1/auth/session') body = { authenticated: true, admin: { username: 'fixture-admin' }, mfa_required: false };
    else if (path === '/api/v1/auth/csrf') body = { csrf_token: 'fixture-csrf' };
    else if (request.method() === 'GET' && path === '/api/v1/subscriptions/') body = { items: created ? [{ ...subscription, current_token_status: revoked ? 'REVOKED' : 'ACTIVE' }] : [], page: 1, page_size: 25, total: created ? 1 : 0 };
    else if (request.method() === 'GET' && path === '/api/v1/access-profiles/') body = { items: [], page: 1, page_size: 25, total: 0 };
    else if (request.method() === 'POST' && path === '/api/v1/access-profiles/') {
      expect(request.headers()['idempotency-key']).toMatch(/^[a-f0-9-]{36}$/);
      expect(request.postDataJSON().name).toBe(profile.name);
      writes.push('create'); body = profile;
    } else if (path.endsWith('/subscription/')) {
      writes.push('issue'); created = true;
      body = { subscription_id: subscription.id, token: 'fixture-memory-only', url: 'https://example.test/s/fixture-only', display_once: true };
    } else if (request.method() === 'GET' && path === `/api/v1/subscriptions/${subscription.id}/tokens/`) {
      body = {
        items: [{ ...token, status: revoked ? 'REVOKED' : 'ACTIVE', revoked_at: revoked ? '2026-11-06T08:05:00Z' : null }],
        page: 1,
        page_size: 25,
        total: 1,
      };
    } else if (request.method() === 'POST' && path === '/api/v1/operations/previews/') {
      expect(request.postDataJSON()).toEqual({
        kind: 'subscription.token_revoke',
        target_id: token.id,
        params: { subscription_id: subscription.id, token_id: token.id },
      });
      writes.push('preview');
      body = preview;
    } else if (request.method() === 'POST' && path === `/api/v1/subscriptions/${subscription.id}/tokens/${token.id}/revoke/`) {
      expect(request.headers()['idempotency-key']).toMatch(/^[a-f0-9-]{36}$/);
      expect(request.postDataJSON()).toEqual({
        preview_id: preview.id,
        confirmation: preview.required_phrase,
      });
      writes.push('revoke');
      revoked = true;
      body = { ...token, status: 'REVOKED', revoked_at: '2026-11-06T08:05:00Z', is_current: false };
    } else throw new Error(`Unexpected test API route ${path}`);
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto('/subscriptions');
  await expect(page.getByRole('heading', { name: '订阅池', exact: true })).toBeVisible();
  await expect(page.getByText('到期 / 额度状态', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '创建订阅', exact: true }).click();
  const editor = page.getByRole('dialog', { name: '创建订阅', exact: true });
  await editor.getByLabel('名称', { exact: true }).fill(profile.name);
  await editor.getByRole('button', { name: '保存订阅', exact: true }).click();
  const delivery = page.getByRole('dialog', { name: '一次性交付', exact: false });
  await expect(delivery.getByText('fixture-memory-only', { exact: true })).toBeVisible();
  await delivery.getByRole('button', { name: '我已安全保存并关闭' }).click();
  await expect(page.getByText('尚未采集', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Token 历史', exact: true }).click();
  await page.getByRole('button', { name: '撤销此 Token', exact: true }).click();
  const revokeDialog = page.getByRole('dialog');
  await expect(revokeDialog).toBeVisible();
  await revokeDialog.getByLabel('确认文本', { exact: true }).fill(preview.required_phrase);
  await revokeDialog.getByTestId('danger-submit').click();
  await expect(page.getByRole('button', { name: '撤销此 Token', exact: true })).toHaveCount(0);
  expect(writes).toEqual(['create', 'issue', 'preview', 'revoke']);
  const browserValues = await page.evaluate(() => JSON.stringify([Object.values(localStorage), Object.values(sessionStorage)]));
  expect(browserValues).not.toContain('fixture-memory-only');
  expect(browserValues).not.toContain('fixture-only');
  await expect(page.getByText('fixture-memory-only', { exact: true })).toHaveCount(0);
});

test('opens the name-only editor and publication history controls', async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown;
    if (path === '/api/v1/auth/session') body = { authenticated: true, admin: { username: 'fixture-admin' }, mfa_required: false };
    else if (path === '/api/v1/subscriptions/') body = { items: [subscription], total: 1, page: 1, page_size: 25 };
    else if (path.startsWith('/api/v1/access-profiles/')) body = { items: [], total: 0, page: 1, page_size: 25 };
    else if (path === `/api/v1/subscriptions/${subscription.id}/`) body = { ...subscription, profile, assignments: [], revisions: [] };
    else throw new Error('Unexpected fixture request');
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto('/subscriptions');
  await expect(page.getByText('到期 / 额度状态', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '管理', exact: true }).click();
  const editor = page.getByRole('dialog', { name: '管理订阅' });
  await expect(editor.getByLabel('名称', { exact: true })).toHaveValue(profile.name);
  await expect(editor.getByRole('tab', { name: '套餐管理' })).toHaveCount(0);
  await expect(editor.getByRole('tab', { name: '节点协议', exact: true })).toHaveCount(0);
  await editor.getByRole('tab', { name: '发布历史' }).click();
  await expect(editor.getByText('目标代数', { exact: true })).toBeVisible();
});
