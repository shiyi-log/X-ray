import { expect, test } from '@playwright/test';

import {
  completePartialRevocation,
  removeTraceNetworkArchive,
  screenshotPath,
  tracePath,
} from './helpers';

test.setTimeout(90_000);

test('管理员从会话恢复完成一次性交付与部分撤销全流程', async ({ page, context }) => {
  const profileName = `e2e-full-flow-${Date.now()}`;
  const sanitizedTrace = tracePath('full-flow-sanitized.zip');
  let traceError: Error | null = null;
  let traceSaved = false;
  await context.tracing.start({ screenshots: true, snapshots: true, sources: false });

  try {
    await page.goto('/overview');
    await page.reload();
    await expect(page.getByText('当前管理员')).toBeVisible();
    await expect(page.getByText('e2e-owner')).toBeVisible();
    await expect(page.getByText('安全屏障')).toBeVisible();

    const pages = [
      ['云账号', '云账号', '暂无云账号'],
      ['节点池', '节点池', '暂无节点池'],
      ['节点', '节点', '暂无节点'],
      ['操作中心', '操作中心', 'node.create'],
      ['审计', '审计日志', 'e2e.seed.complete'],
      ['系统', '系统设置', '部署配置只读'],
    ] as const;
    for (const [navigation, heading, visibleText] of pages) {
      await page.getByRole('link', { name: navigation, exact: true }).click();
      await expect(page.getByRole('heading', { name: heading })).toBeVisible();
      await expect(page.getByText(visibleText, { exact: true }).first()).toBeVisible();
    }

    await page.getByRole('link', { name: '访问配置', exact: true }).click();
    await page.getByRole('button', { name: '新建访问配置' }).click();
    const createDialog = page.getByRole('dialog', { name: '新建访问配置' });
    await createDialog.getByLabel('名称').fill(profileName);
    await createDialog.getByRole('button', { name: '创建', exact: true }).click();

    const profileRow = page.getByRole('row').filter({ hasText: profileName });
    await expect(profileRow).toBeVisible();
    await profileRow.getByRole('button', { name: '签发 Token' }).click();
    const delivery = page.getByRole('dialog', { name: '一次性交付' });
    const token = (await delivery.locator('.secret-value code').textContent()) || '';
    expect(token).toHaveLength(43);
    expect(await page.evaluate(() => ({ ...localStorage }))).toEqual({});
    expect(await page.evaluate(() => ({ ...sessionStorage }))).toEqual({});
    await delivery.getByRole('button', { name: '我已安全保存并关闭' }).click();
    await page.reload();
    await expect(page.getByText(token, { exact: true })).toHaveCount(0);

    await page.getByRole('link', { name: '订阅', exact: true }).click();
    await expect(page).toHaveURL(/\/subscriptions$/);
    await expect(page.getByRole('heading', { name: '订阅' })).toBeVisible();
    const subscriptionRow = page.getByRole('row').filter({ hasText: profileName });
    await expect(subscriptionRow).toBeVisible();

    await context.setOffline(true);
    await page.getByRole('button', { name: '刷新' }).click();
    await expect(page.getByRole('alert')).toBeVisible();
    await context.setOffline(false);
    await page.getByRole('button', { name: '刷新' }).click();
    await expect(subscriptionRow).toBeVisible();

    await subscriptionRow.getByRole('button', { name: '强制撤销访问' }).click();
    const revokeDialog = page.getByRole('dialog', { name: '强制撤销访问' });
    await revokeDialog.getByLabel('确认文本').fill('确认强制撤销');
    await revokeDialog.getByRole('button', { name: '提交操作' }).click();
    await expect(page).toHaveURL(/\/operations\/[0-9a-f-]+$/);
    const operationId = page.url().split('/').pop()!;
    completePartialRevocation(operationId);
    await page.reload();
    await expect(page.getByText('链接已撤销', { exact: true })).toBeVisible();
    await expect(page.getByText('节点访问撤销未确认', { exact: true })).toBeVisible();
    await expect(page.getByText('全部旧凭据已失效', { exact: true })).toHaveCount(0);
    await page.screenshot({
      path: screenshotPath('desktop-full-flow-partial-revocation.png'),
      fullPage: true,
    });
  } finally {
    await context.setOffline(false).catch(() => undefined);
    try {
      await context.tracing.stop({ path: sanitizedTrace });
      traceSaved = true;
    } catch (error) {
      traceError = error instanceof Error ? error : new Error(String(error));
    }
  }
  if (traceSaved) removeTraceNetworkArchive(sanitizedTrace);
  expect(traceError, traceError?.message).toBeNull();
});
