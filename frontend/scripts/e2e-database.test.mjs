import assert from 'node:assert/strict';
import test from 'node:test';

import * as e2eDatabase from './e2e-database.mjs';

const { assertDisposableContainer, runCapturedCommand } = e2eDatabase;

const expected = {
  containerPort: 5432,
  image: 'postgres:17.6-alpine',
  name: 'xray-e2e-postgres-run',
  port: 55433,
  runId: '0b67ed38-25ef-4f52-bd1e-6b2510c2f7e1',
  service: 'postgres',
  tmpfsPath: '/var/lib/postgresql/data',
};

function inspect(overrides = {}) {
  return {
    Name: `/${expected.name}`,
    Config: {
      Image: expected.image,
      Labels: {
        'io.xray.e2e.run-id': expected.runId,
        'io.xray.e2e.service': expected.service,
      },
    },
    State: { Running: true },
    HostConfig: {
      PortBindings: {
        '5432/tcp': [{ HostIp: '127.0.0.1', HostPort: String(expected.port) }],
      },
      Tmpfs: { [expected.tmpfsPath]: 'rw,size=512m' },
      Binds: null,
      Mounts: null,
    },
    Mounts: [],
    NetworkSettings: {
      Ports: {
        '5432/tcp': [{ HostIp: '127.0.0.1', HostPort: String(expected.port) }],
      },
    },
    ...overrides,
  };
}

test('captures successful quiet child-process output', () => {
  const output = runCapturedCommand(process.execPath, ['-e', 'process.stdout.write("ready")']);

  assert.equal(output, 'ready');
});

test('requires backend subprocesses to share the isolated database marker and endpoints', () => {
  const validateEnvironment = e2eDatabase.assertE2eDatabaseEnvironment;
  assert.equal(typeof validateEnvironment, 'function');
  if (typeof validateEnvironment !== 'function') return;

  const environment = {
    XRAY_E2E_RUN_ID: expected.runId,
    XRAY_TEST_DATABASE_URL: `postgresql://xray_e2e@127.0.0.1:${expected.port}/xray_test`,
    XRAY_REDIS_URL: 'redis://127.0.0.1:56380/0',
  };

  assert.doesNotThrow(() => validateEnvironment(environment, expected.runId));
  assert.throws(
    () => validateEnvironment({ ...environment, XRAY_E2E_RUN_ID: '' }, expected.runId),
    /not using the isolated E2E database/,
  );
  assert.throws(
    () =>
      validateEnvironment(
        { ...environment, XRAY_TEST_DATABASE_URL: '' },
        expected.runId,
      ),
    /not using the isolated E2E database/,
  );
});

test('validates isolated E2E database and Redis endpoints on selected ports', () => {
  const environment = {
    XRAY_E2E_RUN_ID: expected.runId,
    XRAY_E2E_POSTGRES_PORT: '9543',
    XRAY_E2E_REDIS_PORT: '9544',
    XRAY_TEST_DATABASE_URL: 'postgresql://xray_e2e@127.0.0.1:9543/xray_test',
    XRAY_REDIS_URL: 'redis://127.0.0.1:9544/0',
  };

  assert.doesNotThrow(() =>
    e2eDatabase.assertE2eDatabaseEnvironment(environment, expected.runId),
  );
});

test('accepts only the expected disposable container on its loopback port', () => {
  assert.doesNotThrow(() => assertDisposableContainer(inspect(), expected));
});

test('rejects a container with a different run label', () => {
  const value = inspect();
  value.Config.Labels['io.xray.e2e.run-id'] = 'another-run';

  assert.throws(() => assertDisposableContainer(value, expected), /not an isolated disposable/);
});

test('rejects a container bound beyond loopback', () => {
  const value = inspect();
  value.HostConfig.PortBindings['5432/tcp'][0].HostIp = '0.0.0.0';

  assert.throws(() => assertDisposableContainer(value, expected), /not an isolated disposable/);
});

test('rejects persistent storage mounted at or beside the temporary data directory', () => {
  const value = inspect({
    Mounts: [
      {
        Type: 'volume',
        Name: 'old-test-data',
        Destination: expected.tmpfsPath,
      },
    ],
  });

  assert.throws(() => assertDisposableContainer(value, expected), /not an isolated disposable/);
});
