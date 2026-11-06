import { execFileSync } from 'node:child_process';

function onlyLoopbackPort(bindings, port) {
  return (
    Array.isArray(bindings) &&
    bindings.length === 1 &&
    bindings[0]?.HostIp === '127.0.0.1' &&
    bindings[0]?.HostPort === String(port)
  );
}

const POSTGRES_PORT = 55433;
const REDIS_PORT = 56380;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function runCapturedCommand(command, args) {
  return execFileSync(command, args, {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  }).trim();
}

export function assertE2eDatabaseEnvironment(environment, runId) {
  const valid =
    typeof runId === 'string' &&
    UUID_PATTERN.test(runId) &&
    environment?.XRAY_E2E_RUN_ID === runId &&
    environment?.XRAY_TEST_DATABASE_URL ===
      `postgresql://xray_e2e@127.0.0.1:${POSTGRES_PORT}/xray_test` &&
    environment?.XRAY_REDIS_URL === `redis://127.0.0.1:${REDIS_PORT}/0`;
  if (!valid) {
    throw new Error('backend is not using the isolated E2E database');
  }
}

export function assertDisposableContainer(inspect, expected, { requireRunning = true } = {}) {
  const containerPort = `${expected.containerPort}/tcp`;
  const mounts = inspect?.Mounts ?? [];
  const tmpfsMountsOnly = mounts.every(
    (mount) => mount.Type === 'tmpfs' && mount.Destination === expected.tmpfsPath,
  );
  const binds = inspect?.HostConfig?.Binds ?? [];
  const configuredMounts = inspect?.HostConfig?.Mounts ?? [];
  const tmpfsOptions = inspect?.HostConfig?.Tmpfs?.[expected.tmpfsPath];

  const valid =
    inspect?.Name === `/${expected.name}` &&
    inspect?.Config?.Image === expected.image &&
    inspect?.Config?.Labels?.['io.xray.e2e.run-id'] === expected.runId &&
    inspect?.Config?.Labels?.['io.xray.e2e.service'] === expected.service &&
    (!requireRunning || inspect?.State?.Running === true) &&
    onlyLoopbackPort(inspect?.HostConfig?.PortBindings?.[containerPort], expected.port) &&
    onlyLoopbackPort(inspect?.NetworkSettings?.Ports?.[containerPort], expected.port) &&
    typeof tmpfsOptions === 'string' &&
    /(?:^|,)rw(?:,|$)/.test(tmpfsOptions) &&
    binds.length === 0 &&
    configuredMounts.length === 0 &&
    tmpfsMountsOnly;

  if (!valid) {
    throw new Error('container is not an isolated disposable test service');
  }
}
