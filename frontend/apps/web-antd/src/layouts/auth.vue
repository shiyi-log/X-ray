<script lang="ts" setup>
import { computed } from 'vue';
import { KeyRound, ListChecks, ShieldCheck } from 'lucide-vue-next';

import { preferences, usePreferences } from '@vben/preferences';

const appName = computed(() => preferences.app.name);
const logo = computed(() => preferences.logo.source);
const { isDark } = usePreferences();
</script>

<template>
  <main class="xray-auth" :class="{ dark: isDark }">
    <aside class="xray-auth__brand">
      <div class="xray-auth__brandmark">
        <img :src="logo" :alt="appName" />
        <span class="xray-auth__brandname">{{ appName }}</span>
      </div>

      <div class="xray-auth__statement">
        <p class="xray-auth__eyebrow">管理控制面 · 安全会话</p>
        <h1>管理员控制面<br />安全访问入口</h1>
        <p>密码验证后，按账户状态完成动态验证码或恢复码校验。</p>
      </div>

      <div class="xray-auth__facts" aria-label="会话与操作保护">
        <span class="xray-auth__fact"><KeyRound :size="15" /> 多因素校验</span>
        <span class="xray-auth__fact"><ShieldCheck :size="15" /> 服务端会话</span>
        <span class="xray-auth__fact"><ListChecks :size="15" /> 操作留痕</span>
      </div>
    </aside>

    <section class="xray-auth__panel">
      <div class="xray-auth__identity">
        <img :src="logo" :alt="appName" />
        <span class="xray-auth__brandname">{{ appName }}</span>
      </div>
      <div class="xray-auth__form">
        <RouterView />
        <p class="xray-auth__footer">仅限授权管理员访问 · 会话状态由服务端管理</p>
      </div>
    </section>
  </main>
</template>
