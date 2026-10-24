import type { Locale } from 'ant-design-vue/es/locale';
import type { App } from 'vue';

import { ref } from 'vue';

import {
  $t,
  loadLocalesMapFromDir,
  setupI18n as setupCoreI18n,
} from '@vben/locales';
import { preferences } from '@vben/preferences';

import antdEnLocale from 'ant-design-vue/es/locale/en_US';
import antdZhLocale from 'ant-design-vue/es/locale/zh_CN';

const antdLocale = ref<Locale>(antdZhLocale);
const modules = import.meta.glob('./langs/**/*.json');
const locales = loadLocalesMapFromDir(/\.\/langs\/([^/]+)\/(.*)\.json$/, modules);

async function loadMessages(lang: 'en-US' | 'zh-CN') {
  const message = await locales[lang]?.();
  if (lang === 'en-US') antdLocale.value = antdEnLocale;
  if (lang === 'zh-CN') antdLocale.value = antdZhLocale;
  return message?.default ?? {};
}

async function setupI18n(app: App) {
  await setupCoreI18n(app, {
    defaultLocale: preferences.app.locale,
    loadMessages,
    missingWarn: !import.meta.env.PROD,
  });
}

export { $t, antdLocale, setupI18n };
