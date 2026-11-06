import { execFileSync, spawn } from 'node:child_process';
import path from 'node:path';

import { assertE2eDatabaseEnvironment } from '../../scripts/e2e-database.mjs';

const repositoryDirectory = path.resolve(import.meta.dirname, '../..', '..');
const backendDirectory = path.join(repositoryDirectory, 'backend');
const pythonPath = path.join(backendDirectory, '.venv', 'bin', 'python');
const managePath = path.join(backendDirectory, 'manage.py');
const runId = process.env.XRAY_E2E_RUN_ID;
const backendPort = process.env.XRAY_BACKEND_PORT ?? '9537';
let serverProcess;

assertE2eDatabaseEnvironment(process.env, runId);
execFileSync(process.execPath, [path.resolve(import.meta.dirname, 'prepare-e2e-database.mjs')], {
  cwd: repositoryDirectory,
  env: process.env,
  stdio: 'inherit',
});

serverProcess = spawn(
  pythonPath,
  [managePath, 'runserver', `127.0.0.1:${backendPort}`, '--noreload'],
  { cwd: repositoryDirectory, env: process.env, stdio: 'inherit' },
);

function stopBackend(signal) {
  if (serverProcess && serverProcess.exitCode === null && !serverProcess.killed) {
    serverProcess.kill(signal);
  }
}

process.once('SIGINT', () => stopBackend('SIGINT'));
process.once('SIGTERM', () => stopBackend('SIGTERM'));
serverProcess.once('error', () => {
  process.exitCode = 1;
});
serverProcess.once('exit', (code, signal) => {
  process.exitCode = code ?? (signal ? 1 : 0);
});
