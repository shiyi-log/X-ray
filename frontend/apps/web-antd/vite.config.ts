import { fileURLToPath, URL } from 'node:url';

import { defineConfig } from '@vben/vite-config';

function configuredPort(name: string, fallback: number): number {
  const value = process.env[name];
  if (!value) return fallback;

  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`${name} must be an integer between 1 and 65535.`);
  }
  return port;
}

export default defineConfig(async () => {
  const backendPort = configuredPort('XRAY_BACKEND_PORT', 9527);
  const frontendPort = configuredPort('XRAY_FRONTEND_PORT', 9528);

  return {
    application: {
      archiver: false,
      devtools: false,
      extraAppConfig: false,
      importmap: false,
      injectAppLoading: false,
      injectMetadata: false,
      nitroMock: false,
      print: false,
      pwa: false,
      vxeTableLazyImport: false,
    },
    vite: {
      resolve: {
        dedupe: ['vue', 'vue-router', 'pinia'],
        alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
      },
      server: {
        host: '127.0.0.1',
        port: frontendPort,
        strictPort: true,
        proxy: {
          '/api': `http://127.0.0.1:${backendPort}`,
          '^/s/[A-Za-z0-9_-]{43}': `http://127.0.0.1:${backendPort}`,
        },
      },
    },
  };
});
