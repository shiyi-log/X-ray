import { defineOverridesPreferences } from '@vben/preferences';

import xrayLogo from './assets/xray-logo.svg';

export const overridesPreferences = defineOverridesPreferences({
  app: {
    name: 'X-ray Manager',
    defaultAvatar: xrayLogo,
    defaultHomePath: '/overview',
    enableCheckUpdates: false,
  },
  copyright: {
    companyName: 'X-ray Manager',
    companySiteLink: '',
    date: '2026',
  },
  logo: { enable: true, source: xrayLogo },
  shortcutKeys: { globalLockScreen: false },
  tabbar: { persist: false },
  widget: {
    lockScreen: false,
    notification: false,
  },
});
