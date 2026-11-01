import { expect, test } from '@playwright/test';

import { removeTraceNetworkArchive, screenshotPath, tracePath } from './helpers';

const fixedOperation = '11111111-1111-4111-8111-111111111111';

test('刷新恢复会话、真实空状态与固定 Operation', async ({ page, context }) => {
  await page.goto('/overview');
  await page.reload();
  await expect(page.getByRole('heading', { name: '总览' })).toBeVisible();
  await expect(page.getByText('安全屏障', { exact: true })).toBeVisible();
  await page.goto('/cloud-accounts');
  await expect(page.getByText('暂无云账号')).toBeVisible();
  const sanitizedTrace = tracePath('resource-flow-sanitized.zip');
  await context.tracing.start({ screenshots: true, snapshots: true, sources: false });
  await page.goto(`/operations/${fixedOperation}`);
  await expect(page.getByTestId('operation-id')).toHaveText(fixedOperation);
  await expect(page.getByTestId('operation-state')).toContainText('运行中');
  await page.reload();
  await expect(page.getByTestId('operation-id')).toHaveText(fixedOperation);
  await page.screenshot({ path: screenshotPath('desktop-operation.png'), fullPage: true });
  await context.tracing.stop({ path: sanitizedTrace });
  removeTraceNetworkArchive(sanitizedTrace);
});

test('真实网络失败显示错误且不伪造系统数据', async ({ page, context }) => {
  await page.goto('/subscriptions');
  await expect(page.getByRole('heading', { name: '订阅池' })).toBeVisible();
  const refresh = page.getByRole('button', { name: '刷新' });
  await expect(refresh).toBeVisible();
  await context.setOffline(true);
  await refresh.click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByRole('row').filter({ hasText: 'e2e-revocation-device' })).toHaveCount(0);
  await context.setOffline(false);
});
