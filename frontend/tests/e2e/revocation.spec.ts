import { expect, test } from '@playwright/test';

import { completePartialRevocation, screenshotPath } from './helpers';

test('一次性交付在关闭后从 DOM 清除', async ({ page }) => {
  await page.goto('/access-profiles');
  const row = page.getByRole('row').filter({ hasText: 'e2e-new-device' });
  await row.getByRole('button', { name: '签发 Token' }).click();
  const dialog = page.getByRole('dialog', { name: '一次性交付' });
  await expect(dialog).toBeVisible();
  const token = (await dialog.locator('code').first().textContent()) || '';
  expect(token).toHaveLength(43);
  expect(await page.evaluate(() => Object.values(localStorage))).not.toContain(token);
  expect(await page.evaluate(() => Object.values(sessionStorage))).not.toContain(token);
  await dialog.getByRole('button', { name: '我已安全保存并关闭' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText(token, { exact: true })).toHaveCount(0);
  await page.screenshot({ path: screenshotPath('desktop-access-profiles.png'), fullPage: true });
});

test('危险确认后的 partial result 不宣称全部凭据失效', async ({ page }) => {
  await page.goto('/subscriptions');
  const row = page.getByRole('row').filter({ hasText: 'e2e-revocation-device' });
  await row.getByRole('button', { name: '强制撤销访问' }).click();
  const dialog = page.getByRole('dialog', { name: '强制撤销访问' });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel('确认文本').fill('确认强制撤销');
  await dialog.getByRole('button', { name: '提交操作' }).click();
  await expect(page).toHaveURL(/\/operations\/[0-9a-f-]+$/);
  const operationId = page.url().split('/').pop()!;
  completePartialRevocation(operationId);
  await page.reload();
  await expect(page.getByText('链接已撤销', { exact: true })).toBeVisible();
  await expect(page.getByText('节点访问撤销未确认', { exact: true })).toBeVisible();
  await expect(page.getByText('全部旧凭据已失效', { exact: true })).toHaveCount(0);
  await page.screenshot({ path: screenshotPath('desktop-partial-revocation.png'), fullPage: true });
});
