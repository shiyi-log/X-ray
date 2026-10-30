<script lang="ts" setup>
import { computed } from 'vue';

import { useAntdDesignTokens } from '@vben/hooks';
import { preferences, usePreferences } from '@vben/preferences';

import { App as AntApp, ConfigProvider, theme } from 'ant-design-vue';

import { antdLocale } from './locales';

defineOptions({ name: 'XrayApp' });

const { isDark } = usePreferences();
const { tokens } = useAntdDesignTokens();

const tokenTheme = computed(() => ({
  algorithm: [
    isDark.value ? theme.darkAlgorithm : theme.defaultAlgorithm,
    ...(preferences.app.compact ? [theme.compactAlgorithm] : []),
  ],
  token: {
    ...tokens,
    colorPrimary: isDark.value ? '#65c9b5' : '#087e78',
    colorSuccess: isDark.value ? '#79c594' : '#397a55',
    colorWarning: isDark.value ? '#e2ad63' : '#ad6819',
    colorError: isDark.value ? '#e28a82' : '#b34742',
    colorBgLayout: isDark.value ? '#151e23' : '#eef2f1',
    colorBgContainer: isDark.value ? '#202b30' : '#ffffff',
    colorText: isDark.value ? '#e7efed' : '#1c2b31',
    colorTextSecondary: isDark.value ? '#a1b0b0' : '#63747a',
    colorBorderSecondary: isDark.value ? '#34444a' : '#dbe4e2',
    borderRadius: 6,
    fontFamily: 'var(--x-font)',
  },
}));
</script>

<template>
  <ConfigProvider :locale="antdLocale" :theme="tokenTheme">
    <AntApp>
      <RouterView />
    </AntApp>
  </ConfigProvider>
</template>
