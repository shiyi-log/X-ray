import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';

const repositoryRoot = path.resolve(import.meta.dirname, '..');
const authState = path.join(import.meta.dirname, '.playwright', 'admin.json');
const acceptanceRoot = path.join(repositoryRoot, 'artifacts', 'acceptance', '0.5.0');
const testEnvironment = {
  ...process.env,
  DJANGO_SETTINGS_MODULE: 'config.settings.test',
  XRAY_ENV: 'test',
  XRAY_TEST_DATABASE_URL:
    process.env.XRAY_TEST_DATABASE_URL ||
    'postgresql://xray_test:xray_test_only_password@127.0.0.1:55432/xray_test',
  XRAY_REDIS_URL: process.env.XRAY_REDIS_URL || 'redis://127.0.0.1:56379/0',
  XRAY_CSRF_TRUSTED_ORIGINS: 'http://127.0.0.1:5178',
};

export default defineConfig({
  testDir: './tests/e2e',
  outputDir: path.join(acceptanceRoot, 'test-results'),
  globalSetup: './tests/e2e/global-setup.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['json', { outputFile: path.join(acceptanceRoot, 'playwright-report.json') }]],
  use: {
    baseURL: 'http://127.0.0.1:5178',
    channel: 'chrome',
    trace: 'off',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  webServer: [
    {
      command: '../backend/.venv/bin/python ../backend/manage.py runserver 127.0.0.1:8000 --noreload',
      url: 'http://127.0.0.1:8000/health/live',
      reuseExistingServer: false,
      timeout: 120_000,
      env: testEnvironment,
    },
    {
      command: 'pnpm dev',
      url: 'http://127.0.0.1:5178/login',
      reuseExistingServer: false,
      timeout: 120_000,
      env: testEnvironment,
    },
  ],
  projects: [
    {
      name: 'setup',
      testMatch: /auth\.setup\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'desktop-chromium',
      dependencies: ['setup'],
      testIgnore: [/auth\.setup\.ts/, /mobile\.spec\.ts/],
      use: {
        ...devices['Desktop Chrome'],
        storageState: authState,
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: 'mobile-chromium',
      dependencies: ['setup'],
      testMatch: /mobile\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        storageState: authState,
        viewport: { width: 390, height: 844 },
        isMobile: true,
      },
    },
  ],
});

export { acceptanceRoot, authState, testEnvironment };
