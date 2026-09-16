<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { Plus, RefreshCw } from 'lucide-vue-next';

import { resourcesApi, type CloudAccount, type NodePool } from '@/api/resources';
import PageHeader from '@/components/PageHeader.vue';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const router = useRouter();
const { data, loading, error, reload } = useResource(resourcesApi.nodes);
const open = ref(false);
const saving = ref(false);
const formError = ref('');
const pools = ref<NodePool[]>([]);
const accounts = ref<CloudAccount[]>([]);
const form = reactive({ pool_id: '', account_id: '', region: '', plan_id: '', image_id: '' });
const empty = computed(() => !data.value?.items.length);

async function openCreate() {
  open.value = true;
  formError.value = '';
  try {
    const [poolPage, accountPage] = await Promise.all([
      resourcesApi.nodePools(),
      resourcesApi.cloudAccounts(),
    ]);
    pools.value = poolPage.items;
    accounts.value = accountPage.items.filter((item) => item.enabled);
  } catch (caught) {
    formError.value = caught instanceof Error ? caught.message : '依赖数据加载失败';
  }
}

async function createNode() {
  saving.value = true;
  formError.value = '';
  try {
    const result = await resourcesApi.createNode({ ...form }, crypto.randomUUID());
    open.value = false;
    await router.push(`/operations/${result.operation_id}`);
  } catch (caught) {
    formError.value = caught instanceof Error ? caught.message : '提交失败';
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <PageHeader title="节点" subtitle="云状态、服务状态与安全状态分开展示">
    <template #actions>
      <button class="icon-button" title="刷新" aria-label="刷新" @click="reload"><RefreshCw :size="17" /></button>
      <button class="command" @click="openCreate"><Plus :size="17" />创建节点</button>
    </template>
  </PageHeader>
  <PageState :loading="loading" :error="error" :empty="empty" empty-text="暂无节点" @retry="reload">
    <div class="table-wrap"><table><thead><tr><th>节点</th><th>平台/区域</th><th>云原始状态</th><th>部署</th><th>健康</th><th>安全</th><th>Generation</th></tr></thead><tbody><tr v-for="item in data?.items" :key="item.id"><td><strong>{{ item.name }}</strong><small class="resource-id">{{ item.external_id || item.id }}</small></td><td>{{ item.provider }}<small class="resource-id">{{ item.region }}</small></td><td><StatusBadge :value="item.raw_cloud_state || 'UNKNOWN'" /></td><td><StatusBadge :value="item.provisioning_state" /></td><td><StatusBadge :value="item.health_state" /></td><td><StatusBadge :value="item.security_state" /></td><td>{{ item.applied_generation }} / {{ item.desired_generation }}</td></tr></tbody></table></div>
  </PageState>
  <a-modal v-model:open="open" title="创建节点" :footer="null">
    <form class="dialog-form" @submit.prevent="createNode">
      <div v-if="formError" class="form-error">{{ formError }}</div>
      <label>节点池<select v-model="form.pool_id" required><option value="" disabled>请选择</option><option v-for="item in pools" :key="item.id" :value="item.id" :disabled="!item.allow_create || item.available < 1">{{ item.name }}（可用 {{ item.available }}）</option></select></label>
      <label>云账号<select v-model="form.account_id" required><option value="" disabled>请选择</option><option v-for="item in accounts" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
      <label>区域<input v-model="form.region" required /></label>
      <label>套餐 ID<input v-model="form.plan_id" required /></label>
      <label>镜像 ID<input v-model="form.image_id" required /></label>
      <button class="command" :disabled="saving">{{ saving ? '提交中' : '提交创建操作' }}</button>
    </form>
  </a-modal>
</template>

<style scoped src="../styles/resource-page.css"></style>
