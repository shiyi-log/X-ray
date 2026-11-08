import { defineConfig, devices } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import { resolveE2ePorts } from './scripts/e2e-ports.mjs';

const repositoryRoot = path.resolve(import.meta.dirname, '..');
const acceptanceRoot =
  process.env.XRAY_ACCEPTANCE_ARTIFACT_DIR ??
  path.join(repositoryRoot, 'artifacts', 'acceptance', '0.14.4');
const authState =
  process.env.XRAY_PLAYWRIGHT_AUTH_STATE ??
  path.join(import.meta.dirname, '.playwright', 'admin.json');
const { frontendPort, backendPort, postgresPort, redisPort } = resolveE2ePorts();
const e2eRunId = process.env.XRAY_E2E_RUN_ID || randomUUID();
process.env.XRAY_E2E_RUN_ID = e2eRunId;
const frontendOrigin = `http://127.0.0.1:${frontendPort}`;
const testEnvironment = {
  ...process.env,
  DJANGO_SETTINGS_MODULE: 'config.settings.test',
  XRAY_ENV: 'test',
  XRAY_FRONTEND_PORT: String(frontendPort),
  XRAY_BACKEND_PORT: String(backendPort),
  XRAY_E2E_POSTGRES_PORT: String(postgresPort),
  XRAY_E2E_REDIS_PORT: String(redisPort),
  XRAY_TEST_DATABASE_URL: `postgresql://xray_e2e@127.0.0.1:${postgresPort}/xray_test`,
  XRAY_REDIS_URL: `redis://127.0.0.1:${redisPort}/0`,
  XRAY_E2E_RUN_ID: e2eRunId,
  XRAY_CSRF_TRUSTED_ORIGINS: frontendOrigin,
};

export default defineConfig({
  testDir: './tests/e2e',
  outputDir: path.join(acceptanceRoot, 'test-results'),
  globalSetup: './tests/e2e/global-setup.ts',
  fullyParallel: false,
  globalTeardown: './tests/e2e/global-teardown.ts',
  workers: 1,
  retries: 0,
  reporter: [['list'], ['json', { outputFile: path.join(acceptanceRoot, 'playwright-report.json') }]],
  use: {
    baseURL: frontendOrigin,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
  webServer: [
    {
      command: 'node ./tests/e2e/start-backend.mjs',
      url: `http://127.0.0.1:${backendPort}/health/live`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: testEnvironment,
    },
    {
      command: 'corepack pnpm --filter @xray/web-antd run dev',
      url: `${frontendOrigin}/login`,
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
