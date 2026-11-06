import { spawnSync } from 'node:child_process';
import net from 'node:net';
import path from 'node:path';

import {
  assertDisposableContainer,
  assertE2eDatabaseEnvironment,
  runCapturedCommand,
} from '../../scripts/e2e-database.mjs';

const POSTGRES_IMAGE = 'postgres:17.6-alpine';
const REDIS_IMAGE = 'redis:7.4-alpine';
const POSTGRES_PORT = 55433;
const REDIS_PORT = 56380;
const CONTAINER_LABEL_RUN = 'io.xray.e2e.run-id';
const CONTAINER_LABEL_SERVICE = 'io.xray.e2e.service';
const repositoryDirectory = path.resolve(import.meta.dirname, '../..', '..');
const backendDirectory = path.join(repositoryDirectory, 'backend');
const pythonPath = path.join(backendDirectory, '.venv', 'bin', 'python');
const managePath = path.join(backendDirectory, 'manage.py');
const runId = process.env.XRAY_E2E_RUN_ID;
const postgresName = `xray-e2e-postgres-${runId}`;
const redisName = `xray-e2e-redis-${runId}`;
const services = [];

function docker(args) {
  return runCapturedCommand('docker', args);
}

function inspectContainer(id) {
  return JSON.parse(docker(['inspect', '--format', '{{json .}}', id]));
}

function expectedService({ name, image, service, port, containerPort, tmpfsPath }) {
  return { name, image, service, port, containerPort, tmpfsPath, runId };
}

function removeOwnedServices() {
  for (const service of [...services].reverse()) {
    try {
      const inspect = inspectContainer(service.id);
      assertDisposableContainer(inspect, service.expected, { requireRunning: false });
      docker(['rm', '--force', inspect.Id]);
    } catch {
      // Never remove a container that no longer matches this run's identity.
    }
  }
}

function startContainer(name, expected, args) {
  const id = docker(['run', '--detach', '--rm', '--name', name, ...args]);
  const service = { id, expected };
  services.push(service);
  assertDisposableContainer(inspectContainer(id), expected);
  return id;
}

async function assertPortAvailable(port) {
  const listener = net.createServer();
  await new Promise((resolve, reject) => {
    listener.once('error', reject);
    listener.listen(port, '127.0.0.1', resolve);
  });
  await new Promise((resolve, reject) =>
    listener.close((error) => (error ? reject(error) : resolve())),
  );
}

async function waitForReadiness(containerId, args, timeoutMs = 45_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      docker(['exec', containerId, ...args]);
      return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }
  throw new Error('An isolated E2E service did not become ready.');
}

function runPython(args) {
  const result = spawnSync(pythonPath, [managePath, ...args], {
    cwd: repositoryDirectory,
    env: process.env,
    stdio: 'inherit',
  });
  if (result.error || result.status !== 0) {
    throw new Error('E2E database initialization failed.');
  }
}

async function main() {
  assertE2eDatabaseEnvironment(process.env, runId);
  await assertPortAvailable(POSTGRES_PORT);
  await assertPortAvailable(REDIS_PORT);

  const postgresExpected = expectedService({
    name: postgresName,
    image: POSTGRES_IMAGE,
    service: 'postgres',
    port: POSTGRES_PORT,
    containerPort: 5432,
    tmpfsPath: '/var/lib/postgresql/data',
  });
  const redisExpected = expectedService({
    name: redisName,
    image: REDIS_IMAGE,
    service: 'redis',
    port: REDIS_PORT,
    containerPort: 6379,
    tmpfsPath: '/data',
  });

  const postgresId = startContainer(postgresName, postgresExpected, [
    '--label', `${CONTAINER_LABEL_RUN}=${runId}`,
    '--label', `${CONTAINER_LABEL_SERVICE}=postgres`,
    '--publish', `127.0.0.1:${POSTGRES_PORT}:5432`,
    '--tmpfs', '/var/lib/postgresql/data:rw,nosuid,nodev,noexec,size=512m',
    '--env', 'POSTGRES_DB=xray_test',
    '--env', 'POSTGRES_USER=xray_e2e',
    '--env', 'POSTGRES_HOST_AUTH_METHOD=trust',
    POSTGRES_IMAGE,
    'postgres',
    '-c',
    `xray.e2e_run_id=${runId}`,
  ]);
  const redisId = startContainer(redisName, redisExpected, [
    '--label', `${CONTAINER_LABEL_RUN}=${runId}`,
    '--label', `${CONTAINER_LABEL_SERVICE}=redis`,
    '--publish', `127.0.0.1:${REDIS_PORT}:6379`,
    '--tmpfs', '/data:rw,nosuid,nodev,noexec,size=32m',
    REDIS_IMAGE,
    'redis-server',
    '--save',
    '',
    '--appendonly',
    'no',
  ]);

  await waitForReadiness(postgresId, ['pg_isready', '-U', 'xray_e2e', '-d', 'xray_test']);
  await waitForReadiness(redisId, ['redis-cli', 'ping']);
  runPython(['migrate', '--noinput']);
  runPython(['seed_e2e', '--reset']);
}

process.once('SIGINT', () => {
  removeOwnedServices();
  process.exitCode = 130;
});
process.once('SIGTERM', () => {
  removeOwnedServices();
  process.exitCode = 143;
});

main().catch((error) => {
  removeOwnedServices();
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
