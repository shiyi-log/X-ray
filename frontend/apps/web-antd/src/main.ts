import { initPreferences } from '@vben/preferences';
import { unmountGlobalLoading } from '@vben/utils';

import { overridesPreferences } from './preferences';

async function initApplication() {
  const mode = import.meta.env.PROD ? 'prod' : 'dev';
  // Apply the restored template defaults without deleting previous preference data.
  const namespace = `xray-manager-v5.7.0-${mode}`;

  await initPreferences({
    namespace,
    overrides: overridesPreferences,
  });
  const { bootstrap } = await import('./bootstrap');
  await bootstrap(namespace);
  unmountGlobalLoading();
}

void initApplication();
