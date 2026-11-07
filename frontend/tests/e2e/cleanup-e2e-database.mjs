import {
  assertDisposableContainer,
  runCapturedCommand,
} from '../../scripts/e2e-database.mjs';
import { resolveE2ePorts } from '../../scripts/e2e-ports.mjs';

const { postgresPort: POSTGRES_PORT, redisPort: REDIS_PORT } = resolveE2ePorts();
const runId = process.env.XRAY_E2E_RUN_ID;

function docker(args) {
  return runCapturedCommand('docker', args);
}

function cleanupService({ name, image, service, port, containerPort, tmpfsPath }) {
  const expected = { name, image, service, port, containerPort, tmpfsPath, runId };
  let inspect;
  try {
    inspect = JSON.parse(docker(['inspect', '--format', '{{json .}}', name]));
  } catch {
    return;
  }
  assertDisposableContainer(inspect, expected, { requireRunning: false });
  docker(['rm', '--force', inspect.Id]);
}

if (!runId) throw new Error('E2E cleanup requires a run identifier.');

cleanupService({
  name: `xray-e2e-redis-${runId}`,
  image: 'redis:7.4-alpine',
  service: 'redis',
  port: REDIS_PORT,
  containerPort: 6379,
  tmpfsPath: '/data',
});
cleanupService({
  name: `xray-e2e-postgres-${runId}`,
  image: 'postgres:17.6-alpine',
  service: 'postgres',
  port: POSTGRES_PORT,
  containerPort: 5432,
  tmpfsPath: '/var/lib/postgresql/data',
});
