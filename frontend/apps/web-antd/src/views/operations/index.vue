<script setup lang="ts">
import { computed } from 'vue';
import { RefreshCw } from 'lucide-vue-next';

import { resourcesApi } from '@/api/resources';
import PageHeader from '@/components/PageHeader.vue';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const { data, loading, error, reload } = useResource(resourcesApi.operations);
const empty = computed(() => !data.value?.items.length);
</script>

<template>
  <PageHeader title="操作中心" subtitle="所有副作用操作的持久状态">
    <template #actions>
      <button class="icon-button" title="刷新" aria-label="刷新" @click="reload"><RefreshCw :size="17" /></button>
    </template>
  </PageHeader>
  <PageState :loading="loading" :error="error" :empty="empty" empty-text="暂无操作" @retry="reload">
    <div class="table-wrap"><table><thead><tr><th>操作</th><th>目标</th><th>状态</th><th>当前步骤</th><th>更新时间</th></tr></thead><tbody><tr v-for="item in data?.items" :key="item.id"><td><RouterLink :to="`/operations/${item.id}`"><strong>{{ item.kind }}</strong></RouterLink><small class="resource-id">{{ item.id }}</small></td><td>{{ item.target_type }}<small class="resource-id">{{ item.target_id }}</small></td><td><StatusBadge :value="item.status" /></td><td>{{ item.current_step || '-' }}</td><td>{{ item.updated_at ? new Date(item.updated_at).toLocaleString('zh-CN') : '-' }}</td></tr></tbody></table></div>
  </PageState>
</template>

<style scoped src="../styles/resource-page.css"></style>
