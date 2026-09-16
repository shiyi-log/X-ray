<script setup lang="ts">
import { resourcesApi } from '@/api/resources';
import PageHeader from '@/components/PageHeader.vue';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const { data, loading, error, reload } = useResource(resourcesApi.system);
</script>

<template>
  <PageHeader title="系统设置" subtitle="部署配置只读" />
  <PageState :loading="loading" :error="error" @retry="reload">
    <dl class="settings-list">
      <div><dt>版本</dt><dd>{{ data?.version }}</dd></div>
      <div><dt>环境</dt><dd>{{ data?.environment }}</dd></div>
      <div><dt>调试模式</dt><dd><StatusBadge :value="data?.debug" /></dd></div>
      <div><dt>管理 Host allowlist</dt><dd><code v-for="item in data?.allowed_hosts" :key="item">{{ item }}</code><span v-if="!data?.allowed_hosts?.length">未配置</span></dd></div>
      <div><dt>CSRF 可信来源</dt><dd><code v-for="item in data?.csrf_trusted_origins" :key="item">{{ item }}</code><span v-if="!data?.csrf_trusted_origins?.length">未配置</span></dd></div>
    </dl>
  </PageState>
</template>

<style scoped>
.settings-list { margin: 18px 0 0; border: 1px solid var(--x-border); background: white; }
.settings-list > div { min-height: 58px; display: grid; grid-template-columns: 230px 1fr; align-items: center; padding: 10px 16px; border-bottom: 1px solid var(--x-border); }
.settings-list > div:last-child { border: 0; }
dt { color: var(--x-text-muted); font-size: 12px; }
dd { display: flex; flex-wrap: wrap; gap: 8px; margin: 0; }
code { padding: 3px 7px; background: var(--x-surface-muted); border-radius: 3px; }
@media (max-width: 620px) { .settings-list > div { grid-template-columns: 1fr; gap: 6px; } }
</style>
