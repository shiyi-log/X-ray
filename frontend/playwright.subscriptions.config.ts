import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/subscriptions', workers: 1, retries: 0,
  outputDir: '../artifacts/acceptance/subscriptions-local',
  reporter: [['list']],
  use: { ...devices['Desktop Chrome'], channel: 'chrome', baseURL: 'http://127.0.0.1:9580',
    trace: 'off', screenshot: 'off', video: 'off' },
  webServer: { command: 'pnpm dev', url: 'http://127.0.0.1:9580', reuseExistingServer: false,
    env: { XRAY_FRONTEND_PORT: '9580', XRAY_BACKEND_PORT: '9531' }, timeout: 60000 },
});
