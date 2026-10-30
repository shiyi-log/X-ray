import { createApp, watchEffect } from 'vue';

import { useTitle } from '@vueuse/core';

import { registerAccessDirective } from '@vben/access';
import { registerLoadingDirective } from '@vben/common-ui/es/loading';
import { initStores } from '@vben/stores';
import { preferences } from '@vben/preferences';
import '@vben/styles';
import '@vben/styles/antd';
import '@xray/ui/tokens.css';
import './styles/xray.css';

import App from './App.vue';
import { initComponentAdapter } from './adapter/components';
import { initSetupVbenForm } from './adapter/form';
import { $t, setupI18n } from './locales';
import { initializeStaticAccess, router } from './router';
import { useSessionStore } from './stores/session';

export async function bootstrap(namespace: string) {
  const app = createApp(App);
  initComponentAdapter(app);
  initSetupVbenForm();
  registerLoadingDirective(app, { loading: 'loading', spinning: 'spinning' });

  await setupI18n(app);
  await initStores(app, { namespace });
  registerAccessDirective(app);
  initializeStaticAccess();
  useSessionStore().installUnauthorizedHandler();

  const { initTippy } = await import('@vben/common-ui/es/tippy');
  initTippy(app);

  app.use(router);
  watchEffect(() => {
    if (preferences.app.dynamicTitle) {
      const title = router.currentRoute.value.meta?.title;
      useTitle(`${title ? `${$t(String(title))} - ` : ''}${preferences.app.name}`);
    }
  });
  app.mount('#app');
}
