import assert from 'node:assert/strict';
import { test } from 'node:test';

const portsModule = await import('./e2e-ports.mjs').catch(() => null);

test('E2E ports can be selected from registered environment settings', () => {
  assert.ok(portsModule, 'E2E port resolver is not available');
  assert.deepEqual(
    portsModule.resolveE2ePorts({
      XRAY_E2E_BACKEND_PORT: '9541',
      XRAY_E2E_FRONTEND_PORT: '9542',
      XRAY_E2E_POSTGRES_PORT: '9543',
      XRAY_E2E_REDIS_PORT: '9544',
    }),
    { backendPort: 9541, frontendPort: 9542, postgresPort: 9543, redisPort: 9544 },
  );
});

test('E2E port resolver rejects invalid and overlapping ports', () => {
  assert.ok(portsModule, 'E2E port resolver is not available');
  assert.throws(
    () => portsModule.resolveE2ePorts({ XRAY_E2E_BACKEND_PORT: '0' }),
    /valid TCP port/,
  );
  assert.throws(
    () =>
      portsModule.resolveE2ePorts({
        XRAY_E2E_BACKEND_PORT: '9541',
        XRAY_E2E_REDIS_PORT: '9541',
      }),
    /must be different/,
  );
});
