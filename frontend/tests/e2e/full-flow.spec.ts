import { rmSync } from 'node:fs';

import { expect, test } from '@playwright/test';

import {
  completePartialRevocation,
  removeTraceNetworkArchive,
  screenshotPath,
  traceContainsSecret,
  tracePath,
} from './helpers';

test.setTimeout(90_000);

test('管理员从会话恢复完成一次性交付与部分撤销全流程', async ({ page, context }) => {
  const profileName = `e2e-full-flow-${Date.now()}`;
  const sanitizedTrace = tracePath('full-flow-sanitized.zip');
  let deliveredToken = '';
  let traceError: Error | null = null;
  let traceStarted = false;
  rmSync(sanitizedTrace, { force: true });

  try {
    await page.goto('/overview');
    await page.reload();
    await expect(page.getByRole('heading', { name: '总览' })).toBeVisible();
    await expect(page.getByText('安全屏障', { exact: true })).toBeVisible();

    const pages = [
      ['/cloud-accounts', '云账号', '暂无云账号'],
      ['/nodes', '服务器管理', '暂无服务器'],
      ['/operations', '操作中心', 'node.create'],
      ['/audit', '审计日志', 'e2e.seed.complete'],
      ['/system', '系统设置', '部署配置只读'],
    ] as const;
    for (const [path, heading, visibleText] of pages) {
      await page.goto(path);
      await expect(page.getByRole('heading', { name: heading })).toBeVisible();
      await expect(page.getByText(visibleText, { exact: true }).first()).toBeVisible();
    }
    await expect(page.getByRole('link', { name: '节点池', exact: true })).toHaveCount(0);

    await page.goto('/subscriptions');
    await page.getByRole('button', { name: '创建 Token' }).click();
    const createDialog = page.getByRole('dialog', { name: '创建 Token' });
    await createDialog.getByLabel('名称').fill(profileName);
    await createDialog.getByRole('button', { name: '保存 Token' }).click();
    const delivery = page.getByRole('dialog', { name: '一次性交付' });
    deliveredToken = (await delivery.locator('code').first().textContent()) || '';
    expect(deliveredToken).toHaveLength(43);
    expect(await page.evaluate(() => Object.values(localStorage))).not.toContain(deliveredToken);
    expect(await page.evaluate(() => Object.values(sessionStorage))).not.toContain(deliveredToken);
    await delivery.getByRole('button', { name: '我已安全保存并关闭' }).click();
    await page.reload();
    await expect(page.getByText(deliveredToken, { exact: true })).toHaveCount(0);
    await context.tracing.start({ screenshots: true, snapshots: true, sources: false });
    traceStarted = true;

    await page
      .getByRole('navigation', { name: '主导航' })
      .getByRole('menuitem', { name: '订阅管理', exact: true })
      .click();
    await expect(page).toHaveURL(/\/subscriptions$/);
    await expect(page.getByRole('heading', { name: '订阅池' })).toBeVisible();
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
    if (traceStarted) {
      try {
        await context.tracing.stop({ path: sanitizedTrace });
        removeTraceNetworkArchive(sanitizedTrace);
        if (traceContainsSecret(sanitizedTrace, deliveredToken)) {
          rmSync(sanitizedTrace, { force: true });
          traceError = new Error('Sanitized trace contained the one-time token and was removed');
        }
      } catch (error) {
        rmSync(sanitizedTrace, { force: true });
        traceError = error instanceof Error ? error : new Error(String(error));
      }
    }
  }
  expect(traceError, traceError?.message).toBeNull();
});
