<script setup lang="ts">
import { resourcesApi } from '@/api/resources';
import PageHeader from '@/components/PageHeader.vue';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const { data, loading, error, reload } = useResource(resourcesApi.overview);
const countLabels: Record<string, string> = {
  cloud_accounts: '云账号',
  node_pools: '节点池',
  nodes: '节点',
  operations_active: '进行中操作',
  access_profiles: '访问配置',
  subscriptions: '订阅',
};
</script>

<template>
  <PageHeader title="总览" subtitle="控制面当前状态" />
  <PageState :loading="loading" :error="error" @retry="reload">
    <section class="security-band">
      <span>安全屏障</span><StatusBadge :value="data?.security_mode" />
    </section>
    <section class="counts" aria-label="资源数量">
      <div v-for="(value, key) in data?.counts" :key="key">
        <span>{{ countLabels[key] || key }}</span><strong>{{ value }}</strong>
      </div>
    </section>
    <div class="overview-grid">
      <section>
        <h2>最近操作</h2>
        <PageState :empty="!data?.recent_operations?.length" empty-text="暂无操作">
          <ul>
            <li v-for="item in data?.recent_operations" :key="String(item.id)">
              <RouterLink :to="`/operations/${item.id}`">{{ item.kind }}</RouterLink>
              <StatusBadge :value="String(item.status)" />
            </li>
          </ul>
        </PageState>
      </section>
      <section>
        <h2>最近审计</h2>
        <PageState :empty="!data?.recent_audit?.length" empty-text="暂无审计">
          <ul>
            <li v-for="item in data?.recent_audit" :key="String(item.id)">
              <span>{{ item.action }}</span><StatusBadge :value="String(item.result)" />
            </li>
          </ul>
        </PageState>
      </section>
    </div>
  </PageState>
</template>

<style scoped>
.security-band { height: 48px; display: flex; align-items: center; justify-content: space-between; margin-top: 18px; padding: 0 14px; border: 1px solid var(--x-border); background: white; font-weight: 600; }
.counts { display: grid; grid-template-columns: repeat(6, minmax(110px, 1fr)); margin-top: 14px; border: 1px solid var(--x-border); background: white; }
.counts div { min-height: 88px; display: flex; flex-direction: column; justify-content: center; padding: 14px 16px; border-right: 1px solid var(--x-border); }
.counts div:last-child { border-right: 0; }
.counts span { color: var(--x-text-muted); font-size: 12px; }
.counts strong { margin-top: 6px; font-size: 24px; }
.overview-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 18px; }
.overview-grid section { background: white; border: 1px solid var(--x-border); }
.overview-grid h2 { margin: 0; padding: 15px 16px; border-bottom: 1px solid var(--x-border); font-size: 14px; }
ul { margin: 0; padding: 0 16px; list-style: none; }
li { min-height: 48px; display: flex; align-items: center; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--x-border); }
li:last-child { border-bottom: 0; }
a { color: var(--x-accent); text-decoration: none; }
@media (max-width: 1050px) { .counts { grid-template-columns: repeat(3, 1fr); } .counts div:nth-child(3) { border-right: 0; } .counts div:nth-child(-n+3) { border-bottom: 1px solid var(--x-border); } }
@media (max-width: 680px) { .counts { grid-template-columns: repeat(2, 1fr); } .counts div:nth-child(3) { border-right: 1px solid var(--x-border); } .counts div:nth-child(even) { border-right: 0; } .counts div:nth-child(-n+4) { border-bottom: 1px solid var(--x-border); } .overview-grid { grid-template-columns: 1fr; } }
</style>
