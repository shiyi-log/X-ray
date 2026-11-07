const DEFAULT_BACKEND_PORT = 9537;
const DEFAULT_FRONTEND_PORT = 9538;
const DEFAULT_POSTGRES_PORT = 55433;
const DEFAULT_REDIS_PORT = 56380;

function readPort(environment, key, fallback) {
  if (environment[key] === undefined || environment[key] === '') return fallback;

  const port = Number(environment[key]);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) {
    throw new Error(`${key} must be a valid TCP port`);
  }
  return port;
}

export function resolveE2ePorts(environment = process.env) {
  const backendPort = readPort(environment, 'XRAY_E2E_BACKEND_PORT', DEFAULT_BACKEND_PORT);
  const frontendPort = readPort(environment, 'XRAY_E2E_FRONTEND_PORT', DEFAULT_FRONTEND_PORT);
  const postgresPort = readPort(environment, 'XRAY_E2E_POSTGRES_PORT', DEFAULT_POSTGRES_PORT);
  const redisPort = readPort(environment, 'XRAY_E2E_REDIS_PORT', DEFAULT_REDIS_PORT);
  const ports = [backendPort, frontendPort, postgresPort, redisPort];

  if (new Set(ports).size !== ports.length) {
    throw new Error('E2E service ports must be different');
  }

  return { backendPort, frontendPort, postgresPort, redisPort };
}
