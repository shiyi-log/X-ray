<script setup lang="ts">
import { computed } from 'vue';
import { RefreshCw } from 'lucide-vue-next';

import { resourcesApi } from '@/api/resources';
import PageHeader from '@/components/PageHeader.vue';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const { data, loading, error, reload } = useResource(resourcesApi.subscriptions);
const empty = computed(() => !data.value?.items.length);
</script>

<template>
  <PageHeader title="订阅" subtitle="当前可用修订与 Token epoch">
    <template #actions><button class="icon-button" title="刷新" aria-label="刷新" @click="reload"><RefreshCw :size="17" /></button></template>
  </PageHeader>
  <PageState :loading="loading" :error="error" :empty="empty" empty-text="暂无订阅" @retry="reload">
    <div class="table-wrap"><table><thead><tr><th>访问配置</th><th>状态</th><th>Token epoch</th><th>修订</th><th>格式</th><th>可用</th></tr></thead><tbody><tr v-for="item in data?.items" :key="item.id"><td><strong>{{ item.profile_name }}</strong><small class="resource-id">{{ item.id }}</small></td><td><StatusBadge :value="item.status" /></td><td>{{ item.token_epoch }}</td><td>{{ item.current_revision || '-' }}</td><td>{{ item.formats?.join(' / ') || '-' }}</td><td><StatusBadge :value="item.revision_usable" /></td></tr></tbody></table></div>
  </PageState>
</template>

<style scoped src="../styles/resource-page.css"></style>
