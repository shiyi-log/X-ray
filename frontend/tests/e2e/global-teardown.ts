import { execFileSync } from 'node:child_process';
import path from 'node:path';

import { testEnvironment } from '../../playwright.config';

export default function globalTeardown() {
  const script = path.resolve(import.meta.dirname, 'cleanup-e2e-database.mjs');
  execFileSync(process.execPath, [script], {
    cwd: path.resolve(import.meta.dirname, '../..'),
    env: testEnvironment,
    stdio: 'inherit',
  });
}
