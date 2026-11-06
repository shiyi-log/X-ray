import { spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import path from 'node:path';

const playwrightCli = path.resolve('node_modules/@playwright/test/cli.js');
const environment = {
  ...process.env,
  XRAY_E2E_RUN_ID: process.env.XRAY_E2E_RUN_ID || randomUUID(),
};
const result = spawnSync(process.execPath, [playwrightCli, 'test', ...process.argv.slice(2)], {
  cwd: process.cwd(),
  env: environment,
  stdio: 'inherit',
});

if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
