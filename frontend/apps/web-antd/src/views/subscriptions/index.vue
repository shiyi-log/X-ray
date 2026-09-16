<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import { RefreshCw, RotateCw, Send, ShieldX } from 'lucide-vue-next';

import {
  resourcesApi,
  type ActionPreview,
  type SecretDelivery as SecretDeliveryValue,
  type Subscription,
} from '@/api/resources';
import { ApiError } from '@/api/request';
import DangerConfirm from '@/components/DangerConfirm.vue';
import PageHeader from '@/components/PageHeader.vue';
import PageState from '@/components/PageState.vue';
import SecretDelivery from '@/components/SecretDelivery.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const router = useRouter();
const { data, loading, error, reload } = useResource(resourcesApi.subscriptions);
const empty = computed(() => !data.value?.items.length);
const delivery = ref<SecretDeliveryValue | null>(null);
const selected = ref<Subscription | null>(null);
const preview = ref<ActionPreview | null>(null);
const dangerOpen = ref(false);
const dangerBusy = ref(false);
const dangerErrorCode = ref('');
const dangerErrorMessage = ref('');
const actionError = ref('');
const busyAction = ref('');

async function rotate(item: Subscription) {
  actionError.value = '';
  busyAction.value = `rotate:${item.id}`;
  try {
    delivery.value = await resourcesApi.rotateSubscription(item.id);
    await reload();
  } catch (caught) {
    actionError.value = caught instanceof Error ? caught.message : '轮换失败';
  } finally {
    busyAction.value = '';
  }
}

async function publish(item: Subscription) {
  actionError.value = '';
  busyAction.value = `publish:${item.id}`;
  try {
    await resourcesApi.publishSubscription(item.id);
    await reload();
  } catch (caught) {
    actionError.value = caught instanceof Error ? caught.message : '发布失败';
  } finally {
    busyAction.value = '';
  }
}

async function refreshPreview() {
  if (!selected.value) return;
  dangerErrorCode.value = '';
  preview.value = await resourcesApi.createPreview({
    kind: 'subscription.revoke',
    target_id: selected.value.profile_id,
    params: { profile_id: selected.value.profile_id },
  });
}

async function openRevoke(item: Subscription) {
  selected.value = item;
  preview.value = null;
  dangerOpen.value = true;
  dangerErrorCode.value = '';
  dangerErrorMessage.value = '';
  try {
    await refreshPreview();
  } catch (caught) {
    dangerErrorMessage.value = caught instanceof Error ? caught.message : '预览失败';
  }
}

async function confirmRevoke(payload: {
  preview_id: string;
  confirmation: string;
  idempotency_key: string;
}) {
  if (!selected.value) return;
  dangerBusy.value = true;
  dangerErrorCode.value = '';
  dangerErrorMessage.value = '';
  try {
    const accepted = await resourcesApi.forceRevoke(
      selected.value.profile_id,
      { preview_id: payload.preview_id, confirmation: payload.confirmation },
      payload.idempotency_key,
    );
    dangerOpen.value = false;
    await router.push(`/operations/${accepted.operation_id}`);
  } catch (caught) {
    if (caught instanceof ApiError) {
      dangerErrorCode.value = caught.code;
      if (caught.status === 409) {
        dangerErrorMessage.value = '预览已失效，已刷新。请重新核对影响范围并输入确认文本。';
        try {
          await refreshPreview();
        } catch (refreshError) {
          dangerErrorMessage.value =
            refreshError instanceof Error ? refreshError.message : '刷新预览失败';
        }
      } else {
        dangerErrorMessage.value = caught.message;
      }
    } else {
      dangerErrorMessage.value = caught instanceof Error ? caught.message : '撤销请求失败';
    }
  } finally {
    dangerBusy.value = false;
  }
}

function closeDanger() {
  dangerOpen.value = false;
  preview.value = null;
  selected.value = null;
  dangerErrorCode.value = '';
  dangerErrorMessage.value = '';
}
</script>

<template>
  <PageHeader title="订阅" subtitle="当前可用修订与 Token epoch">
    <template #actions><button class="icon-button" title="刷新" aria-label="刷新" @click="reload"><RefreshCw :size="17" /></button></template>
  </PageHeader>
  <PageState :loading="loading" :error="error" :empty="empty" empty-text="暂无订阅" @retry="reload">
    <div v-if="actionError" class="page-error" role="alert">{{ actionError }}</div>
    <div class="table-wrap subscription-table"><table><thead><tr><th>访问配置</th><th>状态</th><th>Token epoch</th><th>修订</th><th>格式</th><th>可用</th><th>操作</th></tr></thead><tbody><tr v-for="item in data?.items" :key="item.id"><td data-label="访问配置"><strong>{{ item.profile_name }}</strong><small class="resource-id">{{ item.id }}</small></td><td data-label="状态"><StatusBadge :value="item.status" /></td><td data-label="Token epoch">{{ item.token_epoch }}</td><td data-label="修订">{{ item.current_revision || '-' }}</td><td data-label="格式">{{ item.formats?.join(' / ') || '-' }}</td><td data-label="可用"><StatusBadge :value="item.revision_usable" /></td><td data-label="操作"><div class="row-actions"><button class="link-button" type="button" :disabled="Boolean(busyAction) || item.status !== 'ACTIVE'" @click="rotate(item)"><RotateCw :size="14" />轮换</button><button class="link-button" type="button" :disabled="Boolean(busyAction) || item.status !== 'ACTIVE'" @click="publish(item)"><Send :size="14" />发布</button><button class="link-button danger-link" type="button" :disabled="Boolean(busyAction) || item.status !== 'ACTIVE'" @click="openRevoke(item)"><ShieldX :size="14" />强制撤销访问</button></div></td></tr></tbody></table></div>
  </PageState>
  <DangerConfirm :open="dangerOpen" :preview="preview" :busy="dangerBusy" :error-code="dangerErrorCode" :error-message="dangerErrorMessage" @close="closeDanger" @refresh="refreshPreview" @confirm="confirmRevoke" />
  <SecretDelivery :open="Boolean(delivery)" :delivery="delivery" @close="delivery = null" />
</template>

<style scoped src="../styles/resource-page.css"></style>
<style scoped>
.row-actions { min-width: 240px; display: flex; align-items: center; gap: 12px; }
.row-actions button { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
.row-actions button:disabled { opacity: .45; cursor: not-allowed; }
.danger-link { color: var(--x-danger); }
@media (max-width: 720px) {
  .subscription-table { overflow: visible; border: 0; background: transparent; }
  .subscription-table table, .subscription-table tbody, .subscription-table tr, .subscription-table td { display: block; width: 100%; }
  .subscription-table thead { display: none; }
  .subscription-table tr { margin-bottom: 12px; padding: 5px 12px; border: 1px solid var(--x-border); background: white; }
  .subscription-table td { min-height: 38px; display: grid; grid-template-columns: 100px minmax(0, 1fr); align-items: center; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--x-border); overflow-wrap: anywhere; }
  .subscription-table td:last-child { border-bottom: 0; }
  .subscription-table td::before { content: attr(data-label); color: var(--x-text-muted); font-size: 11px; font-weight: 650; }
  .subscription-table .resource-id { max-width: 100%; }
  .row-actions { min-width: 0; flex-wrap: wrap; gap: 12px; }
}
</style>
