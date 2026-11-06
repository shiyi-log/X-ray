import fs from 'node:fs';
import path from 'node:path';

import { acceptanceRoot, authState } from '../../playwright.config';

export default async function globalSetup() {
  fs.mkdirSync(path.dirname(authState), { recursive: true, mode: 0o700 });
  fs.mkdirSync(path.join(acceptanceRoot, 'screenshots'), { recursive: true });
}
