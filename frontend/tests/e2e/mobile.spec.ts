import { expect, test } from '@playwright/test';

import { screenshotPath } from './helpers';

test('移动端导航与表格不挤压关键操作', async ({ page }) => {
  await page.goto('/overview');
  await page.getByRole('button', { name: '打开导航' }).click();
  await expect(page.getByRole('navigation', { name: '主导航' })).toBeVisible();
  await page.getByRole('link', { name: '订阅' }).click();
  await expect(page.getByRole('heading', { name: '订阅' })).toBeVisible();
  await expect(page.locator('.sidebar')).not.toHaveClass(/open/);
  await page.waitForTimeout(250);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
  await page.screenshot({ path: screenshotPath('mobile-subscriptions.png'), fullPage: true });
});
