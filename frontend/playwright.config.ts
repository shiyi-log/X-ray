import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';

const repositoryRoot = path.resolve(import.meta.dirname, '..');
const acceptanceRoot =
  process.env.XRAY_ACCEPTANCE_ARTIFACT_DIR ??
  path.join(repositoryRoot, 'artifacts', 'acceptance', '0.12.1');
const authState =
  process.env.XRAY_PLAYWRIGHT_AUTH_STATE ??
  path.join(import.meta.dirname, '.playwright', 'admin.json');
function configuredPort(name: string, fallback: number): number {
  const value = process.env[name];
  if (!value) return fallback;

  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`${name} must be an integer between 1 and 65535.`);
  }
  return port;
}

function requiredTestEndpoint(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} must explicitly target the dedicated E2E services.`);
  }
  return value;
}

const frontendPort = configuredPort('XRAY_FRONTEND_PORT', 9528);
const backendPort = configuredPort('XRAY_BACKEND_PORT', 9527);
const frontendOrigin = `http://127.0.0.1:${frontendPort}`;
const testEnvironment = {
  ...process.env,
  DJANGO_SETTINGS_MODULE: 'config.settings.test',
  XRAY_ENV: 'test',
  XRAY_FRONTEND_PORT: String(frontendPort),
  XRAY_BACKEND_PORT: String(backendPort),
  XRAY_TEST_DATABASE_URL: requiredTestEndpoint('XRAY_TEST_DATABASE_URL'),
  XRAY_REDIS_URL: requiredTestEndpoint('XRAY_REDIS_URL'),
  XRAY_CSRF_TRUSTED_ORIGINS: frontendOrigin,
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
    baseURL: frontendOrigin,
    channel: 'chrome',
    trace: 'off',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  webServer: [
    {
      command: `../backend/.venv/bin/python ../backend/manage.py runserver 127.0.0.1:${backendPort} --noreload`,
      url: `http://127.0.0.1:${backendPort}/health/live`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: testEnvironment,
    },
    {
      command: 'pnpm dev',
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
