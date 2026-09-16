<script setup lang="ts">
import { computed } from 'vue';
import { RefreshCw } from 'lucide-vue-next';

import { resourcesApi } from '@/api/resources';
import PageHeader from '@/components/PageHeader.vue';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const { data, loading, error, reload } = useResource(resourcesApi.auditEvents);
const empty = computed(() => !data.value?.items.length);
</script>

<template>
  <PageHeader title="审计日志" subtitle="追加记录，不包含秘密正文">
    <template #actions><button class="icon-button" title="刷新" aria-label="刷新" @click="reload"><RefreshCw :size="17" /></button></template>
  </PageHeader>
  <PageState :loading="loading" :error="error" :empty="empty" empty-text="暂无审计记录" @retry="reload">
    <div class="table-wrap"><table><thead><tr><th>时间</th><th>动作</th><th>目标</th><th>结果</th><th>请求 ID</th></tr></thead><tbody><tr v-for="item in data?.items" :key="item.id"><td>{{ new Date(item.created_at).toLocaleString('zh-CN') }}</td><td><strong>{{ item.action }}</strong></td><td>{{ item.target_type }}<small class="resource-id">{{ item.target_id || '-' }}</small></td><td><StatusBadge :value="item.result" /></td><td class="mono">{{ item.request_id || '-' }}</td></tr></tbody></table></div>
  </PageState>
</template>

<style scoped src="../styles/resource-page.css"></style>
