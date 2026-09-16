<script setup lang="ts">
import { computed, ref } from 'vue';
import { Plus, RefreshCw } from 'lucide-vue-next';

import { resourcesApi } from '@/api/resources';
import PageHeader from '@/components/PageHeader.vue';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const { data, loading, error, reload } = useResource(resourcesApi.accessProfiles);
const open = ref(false);
const name = ref('');
const formError = ref('');
const empty = computed(() => !data.value?.items.length);

async function createProfile() {
  formError.value = '';
  try {
    await resourcesApi.createAccessProfile(name.value);
    name.value = '';
    open.value = false;
    await reload();
  } catch (caught) {
    formError.value = caught instanceof Error ? caught.message : '创建失败';
  }
}
</script>

<template>
  <PageHeader title="访问配置" subtitle="设备与用途身份">
    <template #actions>
      <button class="icon-button" title="刷新" aria-label="刷新" @click="reload"><RefreshCw :size="17" /></button>
      <button class="command" @click="open = true"><Plus :size="17" />新建访问配置</button>
    </template>
  </PageHeader>
  <PageState :loading="loading" :error="error" :empty="empty" empty-text="暂无访问配置" @retry="reload">
    <div class="table-wrap"><table><thead><tr><th>名称</th><th>状态</th><th>活动凭据</th><th>订阅</th><th>发布冻结</th></tr></thead><tbody><tr v-for="item in data?.items" :key="item.id"><td><strong>{{ item.name }}</strong><small class="resource-id">{{ item.id }}</small></td><td><StatusBadge :value="item.status" /></td><td>{{ item.credential_count }}</td><td><StatusBadge :value="item.subscription_status || 'NOT_ISSUED'" /></td><td><StatusBadge :value="item.publishing_frozen" /></td></tr></tbody></table></div>
  </PageState>
  <a-modal v-model:open="open" title="新建访问配置" :footer="null">
    <form class="dialog-form" @submit.prevent="createProfile"><div v-if="formError" class="form-error">{{ formError }}</div><label>名称<input v-model="name" required /></label><button class="command">创建</button></form>
  </a-modal>
</template>

<style scoped src="../styles/resource-page.css"></style>
