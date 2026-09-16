import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

import { acceptanceRoot, authState, testEnvironment } from '../../playwright.config';

export default async function globalSetup() {
  fs.mkdirSync(path.dirname(authState), { recursive: true, mode: 0o700 });
  fs.mkdirSync(path.join(acceptanceRoot, 'screenshots'), { recursive: true });
  const python = path.resolve(import.meta.dirname, '../../../backend/.venv/bin/python');
  const manage = path.resolve(import.meta.dirname, '../../../backend/manage.py');
  const options = {
    cwd: path.resolve(import.meta.dirname, '../../..'),
    env: testEnvironment,
    stdio: 'inherit' as const,
  };
  execFileSync(python, [manage, 'migrate', '--noinput'], options);
  execFileSync(python, [manage, 'seed_e2e', '--reset'], options);
}
