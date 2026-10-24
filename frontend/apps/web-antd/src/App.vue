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
  token: tokens,
}));
</script>

<template>
  <ConfigProvider :locale="antdLocale" :theme="tokenTheme">
    <AntApp>
      <RouterView />
    </AntApp>
  </ConfigProvider>
</template>
