<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import { Plus, Settings, RefreshCw, RotateCw, Send, ShieldX } from 'lucide-vue-next';

import { Page } from '@vben/common-ui';
import { Alert, Button, Card, Input, Space, Table } from 'ant-design-vue';

import {
  resourcesApi,
  type ActionPreview,
  type SecretDelivery as SecretDeliveryValue,
  type Subscription,
} from '@/api/resources';
import { ApiError } from '@/api/request';
import DangerConfirm from '@/components/DangerConfirm.vue';
import PageState from '@/components/PageState.vue';
import SecretDelivery from '@/components/SecretDelivery.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';
import SubscriptionEditor from './SubscriptionEditor.vue';

const editorOpen = ref(false);
const editorId = ref<string>();
function openEditor(id?: string) { editorId.value = id; editorOpen.value = true; }
function usage(item: Subscription) {
  const p = item.policy;
  if (!p?.usage_updated_at) return '尚未采集';
  return `${((p.upload_bytes + p.download_bytes) / 2 ** 30).toFixed(3)} / ${p.traffic_limit_bytes ? (p.traffic_limit_bytes / 2 ** 30).toFixed(1) : '不限量'} GiB`;
}
const router = useRouter();
const page = ref(1);
const search = ref('');
const { data, loading, error, reload } = useResource(() => resourcesApi.subscriptions(page.value, search.value));
function pageChanged(value: {current?: number}) { page.value = value.current || 1; void reload(); }
function searchSubscriptions() { page.value = 1; void reload(); }
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
const columns = [
  { title: '访问配置', key: 'profile_name', dataIndex: 'profile_name' },
  { title: '状态', key: 'status', dataIndex: 'status' },
  { title: '到期 / 额度状态', key: 'policy' },
  { title: '流量', key: 'usage' },
  { title: 'Token epoch', key: 'token_epoch', dataIndex: 'token_epoch' },
  { title: '修订', key: 'current_revision', dataIndex: 'current_revision' },
  { title: '格式', key: 'formats', dataIndex: 'formats' },
  { title: '可用', key: 'revision_usable', dataIndex: 'revision_usable' },
  { title: '操作', key: 'actions' },
];

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
  <Page title="订阅" description="当前可用修订与 Token epoch">
    <template #title><h1 class="mb-2 text-lg font-semibold">订阅</h1></template>
    <template #extra>
      <Space>
        <Button type="primary" @click="openEditor()"><template #icon><Plus :size="16" /></template>创建订阅</Button>
        <Button title="刷新" aria-label="刷新" @click="reload">
          <template #icon><RefreshCw :size="17" /></template>
        </Button>
      </Space>
    </template>
    <Input.Search v-model:value="search" class="mb-4 max-w-sm" placeholder="搜索访问配置名称" allow-clear @search="searchSubscriptions" />
    <PageState :loading="loading" :error="error" :empty="empty" empty-text="暂无订阅" @retry="reload">
      <Alert v-if="actionError" class="mb-4" type="error" show-icon :message="actionError" role="alert" />
      <Card :bordered="false">
        <Table :columns="columns" :data-source="data?.items || []" row-key="id" :pagination="{current: page, pageSize: 25, total: data?.total || 0, showSizeChanger: false}" :scroll="{ x: 'max-content' }" @change="pageChanged">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'profile_name'">
              <strong class="block font-medium">{{ record.profile_name }}</strong>
              <small class="text-muted-foreground">{{ record.id }}</small>
            </template>
            <StatusBadge v-else-if="column.key === 'status'" :value="record.status" />
            <template v-else-if="column.key === 'policy'"><div>{{ record.policy?.expires_at ? new Date(record.policy.expires_at).toLocaleString() : '不限期' }}</div><small>{{ record.policy?.entitlement_state || record.profile_status }}</small></template>
            <template v-else-if="column.key === 'usage'">{{ usage(record as Subscription) }}</template>
            <template v-else-if="column.key === 'token_epoch'">{{ record.token_epoch }}</template>
            <template v-else-if="column.key === 'current_revision'">{{ record.current_revision || '-' }}</template>
            <template v-else-if="column.key === 'formats'">{{ record.formats?.join(' / ') || '-' }}</template>
            <StatusBadge v-else-if="column.key === 'revision_usable'" :value="record.revision_usable" />
            <Space v-else-if="column.key === 'actions'" wrap>
              <Button type="link" @click="openEditor(record.id)"><template #icon><Settings :size="14" /></template>管理</Button>
              <Button type="link" :disabled="Boolean(busyAction) || record.status !== 'ACTIVE'" :loading="busyAction === `rotate:${record.id}`" @click="rotate(record as Subscription)">
                <template #icon><RotateCw :size="14" /></template>
                轮换
              </Button>
              <Button type="link" :disabled="Boolean(busyAction) || record.status !== 'ACTIVE'" :loading="busyAction === `publish:${record.id}`" @click="publish(record as Subscription)">
                <template #icon><Send :size="14" /></template>
                发布
              </Button>
              <Button type="link" danger :disabled="Boolean(busyAction) || record.status !== 'ACTIVE'" @click="openRevoke(record as Subscription)">
                <template #icon><ShieldX :size="14" /></template>
                强制撤销访问
              </Button>
            </Space>
          </template>
        </Table>
      </Card>
    </PageState>
    <SubscriptionEditor :open="editorOpen" :subscription-id="editorId" @close="editorOpen = false" @saved="reload" @delivery="delivery = $event" />
    <DangerConfirm :open="dangerOpen" :preview="preview" :busy="dangerBusy" :error-code="dangerErrorCode" :error-message="dangerErrorMessage" @close="closeDanger" @refresh="refreshPreview" @confirm="confirmRevoke" />
    <SecretDelivery :open="Boolean(delivery)" :delivery="delivery" @close="delivery = null" />
  </Page>
</template>
