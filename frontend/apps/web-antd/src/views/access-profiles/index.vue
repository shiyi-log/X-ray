<script setup lang="ts">
import { computed, ref } from 'vue';
import { KeyRound, Plus, RefreshCw } from 'lucide-vue-next';

import { resourcesApi, type SecretDelivery as SecretDeliveryValue } from '@/api/resources';
import PageHeader from '@/components/PageHeader.vue';
import PageState from '@/components/PageState.vue';
import SecretDelivery from '@/components/SecretDelivery.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const { data, loading, error, reload } = useResource(resourcesApi.accessProfiles);
const open = ref(false);
const name = ref('');
const formError = ref('');
const actionError = ref('');
const issuingId = ref('');
const delivery = ref<SecretDeliveryValue | null>(null);
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

async function issue(profileId: string) {
  actionError.value = '';
  issuingId.value = profileId;
  try {
    delivery.value = await resourcesApi.issueSubscription(profileId);
    await reload();
  } catch (caught) {
    actionError.value = caught instanceof Error ? caught.message : '签发失败';
  } finally {
    issuingId.value = '';
  }
}

function closeDelivery() {
  delivery.value = null;
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
    <div v-if="actionError" class="page-error" role="alert">{{ actionError }}</div>
    <div class="table-wrap"><table><thead><tr><th>名称</th><th>状态</th><th>活动凭据</th><th>订阅</th><th>发布冻结</th><th>操作</th></tr></thead><tbody><tr v-for="item in data?.items" :key="item.id"><td><strong>{{ item.name }}</strong><small class="resource-id">{{ item.id }}</small></td><td><StatusBadge :value="item.status" /></td><td>{{ item.credential_count }}</td><td><StatusBadge :value="item.subscription_status || 'NOT_ISSUED'" /></td><td><StatusBadge :value="item.publishing_frozen" /></td><td><button v-if="!item.subscription_id && item.status === 'ACTIVE'" class="link-button action-link" type="button" :disabled="issuingId === item.id" @click="issue(item.id)"><KeyRound :size="14" />{{ issuingId === item.id ? '签发中' : '签发 Token' }}</button><span v-else class="muted-action">-</span></td></tr></tbody></table></div>
  </PageState>
  <a-modal v-model:open="open" title="新建访问配置" :footer="null">
    <form class="dialog-form" @submit.prevent="createProfile"><div v-if="formError" class="form-error">{{ formError }}</div><label>名称<input v-model="name" required /></label><button class="command">创建</button></form>
  </a-modal>
  <SecretDelivery :open="Boolean(delivery)" :delivery="delivery" @close="closeDelivery" />
</template>

<style scoped src="../styles/resource-page.css"></style>
<style scoped>
.action-link { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
.action-link:disabled { opacity: .55; cursor: wait; }
.muted-action { color: var(--x-text-muted); }
</style>
