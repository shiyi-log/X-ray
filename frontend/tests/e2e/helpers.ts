import { createHmac } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import path from 'node:path';

import { acceptanceRoot, testEnvironment } from '../../playwright.config';

const base32Alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

function decodeBase32(value: string) {
  let bits = '';
  for (const character of value.replace(/=+$/, '').toUpperCase()) {
    bits += base32Alphabet.indexOf(character).toString(2).padStart(5, '0');
  }
  const bytes: number[] = [];
  for (let index = 0; index + 8 <= bits.length; index += 8) {
    bytes.push(Number.parseInt(bits.slice(index, index + 8), 2));
  }
  return Buffer.from(bytes);
}

export function currentTotp(secret = 'JBSWY3DPEHPK3PXP') {
  const counter = Math.floor(Date.now() / 1000 / 30);
  const buffer = Buffer.alloc(8);
  buffer.writeBigUInt64BE(BigInt(counter));
  const digest = createHmac('sha1', decodeBase32(secret)).update(buffer).digest();
  const offset = digest[digest.length - 1]! & 0x0f;
  const binary =
    ((digest[offset]! & 0x7f) << 24) |
    ((digest[offset + 1]! & 0xff) << 16) |
    ((digest[offset + 2]! & 0xff) << 8) |
    (digest[offset + 3]! & 0xff);
  return String(binary % 1_000_000).padStart(6, '0');
}

export function completePartialRevocation(operationId: string) {
  const python = path.resolve(import.meta.dirname, '../../../backend/.venv/bin/python');
  const manage = path.resolve(import.meta.dirname, '../../../backend/manage.py');
  execFileSync(
    python,
    [manage, 'complete_e2e_revocation', '--operation-id', operationId],
    { cwd: path.resolve(import.meta.dirname, '../../..'), env: testEnvironment, stdio: 'inherit' },
  );
}

export function screenshotPath(name: string) {
  return path.join(acceptanceRoot, 'screenshots', name);
}

export function tracePath(name: string) {
  return path.join(acceptanceRoot, name);
}

export function removeTraceNetworkArchive(target: string) {
  const entries = execFileSync('unzip', ['-Z1', target], { encoding: 'utf8' })
    .split('\n')
    .filter((entry) => entry.endsWith('trace.network'));
  if (entries.length) {
    execFileSync('zip', ['-d', target, ...entries], { stdio: 'ignore' });
  }
}
