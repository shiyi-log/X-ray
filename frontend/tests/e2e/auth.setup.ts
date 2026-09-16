import { expect, test as setup } from '@playwright/test';

import { authState } from '../../playwright.config';
import { currentTotp } from './helpers';

setup('使用真实密码与 TOTP 建立服务器会话', async ({ page }) => {
  await page.goto('/login');
  await page.getByTestId('username').fill('e2e-owner');
  await page.getByTestId('password').fill('e2e-only-password');
  await page.getByTestId('password-submit').getByRole('button', { name: '继续' }).click();
  await page.getByTestId('totp-code').fill(currentTotp());
  await page.getByRole('button', { name: '验证并登录' }).click();
  await expect(page).toHaveURL(/\/overview$/);
  await expect(page.getByRole('heading', { name: '总览' })).toBeVisible();
  await page.context().storageState({ path: authState });
});
