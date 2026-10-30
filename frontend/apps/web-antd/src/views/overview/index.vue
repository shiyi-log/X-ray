<script setup lang="ts">
import { computed } from 'vue';
import {
  Activity,
  Cloud,
  Network,
  RefreshCw,
  Rss,
  ShieldCheck,
  Server,
} from 'lucide-vue-next';

import { Page } from '@vben/common-ui';
import { Button } from 'ant-design-vue';

import { resourcesApi } from '@/api/resources';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';
import { formatOverviewTime, overviewEventLabel } from './presentation';

interface RecentOperation {
  id: string;
  kind: string;
  status: string;
  updated_at?: string;
}

interface RecentAudit {
  id: string | number;
  action: string;
  result: string;
  created_at?: string;
}

const { data, loading, error, reload } = useResource(resourcesApi.overview);

const metrics = [
  { key: 'cloud_accounts', label: '云账号', to: '/cloud-accounts', icon: Cloud },
  { key: 'nodes', label: '节点', to: '/nodes', icon: Server },
  { key: 'operations_active', label: '进行中操作', to: '/operations', icon: Activity },
  { key: 'access_profiles', label: '访问配置', to: '/access-profiles', icon: Network },
  { key: 'subscriptions', label: '订阅', to: '/subscriptions', icon: Rss },
] as const;

const metricItems = computed(() =>
  metrics.map((item) => ({
    ...item,
    value: data.value?.counts?.[item.key] ?? 0,
  })),
);

const recentOperations = computed(
  () => (data.value?.recent_operations ?? []) as unknown as readonly RecentOperation[],
);
const recentAudit = computed(
  () => (data.value?.recent_audit ?? []) as unknown as readonly RecentAudit[],
);
const securityMode = computed(() => data.value?.security_mode || 'MAINTENANCE');
const securityDescription = computed(() => {
  if (securityMode.value === 'MAINTENANCE') return '当前处于维护模式';
  if (securityMode.value === 'OPEN') return '安全屏障处于开放状态';
  return '当前控制面运行模式';
});
</script>

<template>
  <Page class="overview-page" title="总览" description="控制面状态与近期变更">
    <template #title>
      <div class="overview-heading">
        <h1>总览</h1>
      </div>
    </template>
    <template #extra>
      <Button title="刷新" aria-label="刷新" @click="reload">
        <template #icon><RefreshCw :size="16" /></template>
      </Button>
    </template>

    <PageState :loading="loading" :error="error" @retry="reload">
      <div class="overview-dashboard" aria-label="控制面总览">
        <section class="overview-security" aria-label="安全屏障状态">
          <div class="overview-security__main">
            <span class="overview-security__icon"><ShieldCheck :size="21" /></span>
            <span>
              <span class="overview-security__label">安全屏障</span>
              <span class="overview-security__title">{{ securityDescription }}</span>
            </span>
          </div>
          <div class="overview-security__mode">
            <span class="overview-security__label">运行模式</span>
            <StatusBadge :value="securityMode" />
          </div>
        </section>

        <section class="overview-metrics" aria-label="资源概况">
          <RouterLink
            v-for="item in metricItems"
            :key="item.key"
            class="overview-metric"
            :to="item.to"
            :aria-label="`${item.label} ${item.value}`"
          >
            <span class="overview-metric__top">
              <span>{{ item.label }}</span>
              <span class="overview-metric__icon"><component :is="item.icon" :size="16" /></span>
            </span>
            <span class="overview-metric__value">{{ item.value }}</span>
          </RouterLink>
        </section>

        <div class="overview-lower">
          <section class="overview-section" aria-labelledby="recent-operations-title">
            <div class="overview-section__heading">
              <h2 id="recent-operations-title">最近操作</h2>
              <RouterLink class="overview-section__link" to="/operations">查看全部</RouterLink>
            </div>
            <div v-if="!recentOperations.length" class="overview-empty">暂无操作记录</div>
            <div v-for="item in recentOperations" :key="item.id" class="overview-row">
              <RouterLink class="overview-row__link" :to="`/operations/${item.id}`">
                <span class="overview-row__title">{{ overviewEventLabel(item.kind) }}</span>
                <span class="overview-row__meta">{{ item.kind }}</span>
              </RouterLink>
              <span class="overview-row__end">
                <time class="overview-row__time">{{ formatOverviewTime(item.updated_at) }}</time>
                <StatusBadge :value="item.status" />
              </span>
            </div>
          </section>

          <section class="overview-section overview-audit" aria-labelledby="recent-audit-title">
            <div class="overview-section__heading">
              <h2 id="recent-audit-title">最近审计</h2>
              <RouterLink class="overview-section__link" to="/audit">查看日志</RouterLink>
            </div>
            <div v-if="!recentAudit.length" class="overview-empty">暂无审计记录</div>
            <div v-for="item in recentAudit" :key="item.id" class="overview-row">
              <span class="overview-audit__mark" aria-hidden="true"></span>
              <span>
                <span class="overview-row__title">{{ overviewEventLabel(item.action) }}</span>
                <span class="overview-row__meta">{{ item.action }}</span>
                <span class="overview-row__meta">{{ formatOverviewTime(item.created_at) }}</span>
              </span>
            </div>
          </section>
        </div>
      </div>
    </PageState>
  </Page>
</template>
