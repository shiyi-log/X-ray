<script setup lang="ts">
import { computed, ref } from 'vue';
import { KeyRound, Plus, Settings, RefreshCw, RotateCw, Send, ShieldX } from 'lucide-vue-next';
import { useRouter } from 'vue-router';

import { Page } from '@vben/common-ui';
import { Alert, Button, Card, Input, Space, Table, Tag } from 'ant-design-vue';

import {
  resourcesApi,
  type AccessProfile,
  type ActionPreview,
  type Page as PageResult,
  type SecretDelivery as SecretDeliveryValue,
  type Subscription,
  type SubscriptionToken,
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
const router = useRouter();
function usage(item: Subscription) {
  const p = item.policy;
  if (!p?.usage_updated_at) return '尚未采集';
  return `已用 ${((p.upload_bytes + p.download_bytes) / 2 ** 30).toFixed(3)} GiB`;
}
const page = ref(1);
const search = ref('');
const { data, loading, error, reload } = useResource(() => resourcesApi.subscriptions(page.value, search.value));
function pageChanged(value: {current?: number}) { page.value = value.current || 1; void reload(); }
function searchSubscriptions() { page.value = 1; void reload(); }
const empty = computed(() => !data.value?.items.length);
const profilePage = ref(1);
const {
  data: profilesData,
  loading: profilesLoading,
  error: profilesError,
  reload: reloadProfiles,
} = useResource(() => resourcesApi.accessProfiles(profilePage.value));
const unissuedProfiles = computed(() =>
  (profilesData.value?.items || []).filter((profile) => !profile.subscription_id),
);
const issuingProfileId = ref('');
const profileColumns = [
  { title: '访问配置', key: 'name', dataIndex: 'name' },
  { title: '状态', key: 'status', dataIndex: 'status' },
  { title: '活动凭据', key: 'credential_count', dataIndex: 'credential_count' },
  { title: '操作', key: 'actions' },
];
function profilePageChanged(value: {current?: number}) {
  profilePage.value = value.current || 1;
  void reloadProfiles();
}
const delivery = ref<SecretDeliveryValue | null>(null);
type SelectedRevoke =
  | { kind: 'token'; subscription: Subscription; token: SubscriptionToken }
  | { kind: 'profile'; subscription: Subscription };
const selectedRevoke = ref<SelectedRevoke | null>(null);
const revokeTitle = computed(() =>
  selectedRevoke.value?.kind === 'profile' ? '强制撤销访问' : '撤销 Token',
);
const revokeDescription = computed(() =>
  selectedRevoke.value?.kind === 'profile'
    ? '撤销整个访问配置并检查关联节点凭据状态。'
    : '仅撤销这个 Token，其他 Token 和订阅池保持有效。',
);
const preview = ref<ActionPreview | null>(null);
const dangerOpen = ref(false);
const dangerBusy = ref(false);
const dangerErrorCode = ref('');
const dangerErrorMessage = ref('');
const actionError = ref('');
const busyAction = ref('');
const expandedRows = ref<string[]>([]);
const tokenResults = ref<Record<string, PageResult<SubscriptionToken>>>({});
const tokenPages = ref<Record<string, number>>({});
const tokenLoading = ref<Record<string, boolean>>({});
const tokenColumns = [
  { title: 'Token', key: 'token_epoch', dataIndex: 'token_epoch' },
  { title: '状态', key: 'status', dataIndex: 'status' },
  { title: '创建时间', key: 'created_at', dataIndex: 'created_at' },
  { title: '失效时间', key: 'revoked_at', dataIndex: 'revoked_at' },
  { title: '操作', key: 'actions' },
];
const columns = [
  { title: 'Token', key: 'profile_name', dataIndex: 'profile_name' },
  { title: '状态', key: 'status', dataIndex: 'status' },
  { title: '流量', key: 'usage' },
  { title: '节点核对', key: 'node_counts' },
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
    if (expandedRows.value.includes(item.id)) {
      tokenPages.value = { ...tokenPages.value, [item.id]: 1 };
      await loadTokens(item.id, 1);
    }
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

function tokensFor(subscriptionId: string) {
  return tokenResults.value[subscriptionId]?.items || [];
}

async function loadTokens(subscriptionId: string, pageNumber = tokenPages.value[subscriptionId] || 1) {
  if (tokenLoading.value[subscriptionId]) return;
  tokenLoading.value = { ...tokenLoading.value, [subscriptionId]: true };
  try {
    const response = await resourcesApi.subscriptionTokens(subscriptionId, pageNumber);
    tokenResults.value = { ...tokenResults.value, [subscriptionId]: response };
    tokenPages.value = { ...tokenPages.value, [subscriptionId]: response.page };
  } catch (caught) {
    actionError.value = caught instanceof Error ? caught.message : 'Token 历史加载失败';
  } finally {
    tokenLoading.value = { ...tokenLoading.value, [subscriptionId]: false };
  }
}

function tokenPageChanged(subscriptionId: string, pageNumber: number) {
  tokenPages.value = { ...tokenPages.value, [subscriptionId]: pageNumber };
  void loadTokens(subscriptionId, pageNumber);
}

async function issueProfile(profile: AccessProfile) {
  if (issuingProfileId.value) return;
  actionError.value = '';
  issuingProfileId.value = profile.id;
  try {
    delivery.value = await resourcesApi.issueSubscription(profile.id);
    await Promise.all([reloadProfiles(), reload()]);
  } catch (caught) {
    actionError.value = caught instanceof Error ? caught.message : 'Token 签发失败';
  } finally {
    issuingProfileId.value = '';
  }
}

async function expandedChanged(expanded: boolean, item: Subscription) {
  expandedRows.value = expanded
    ? [...new Set([...expandedRows.value, item.id])]
    : expandedRows.value.filter((id) => id !== item.id);
  if (expanded) await loadTokens(item.id);
}

async function toggleTokens(item: Subscription) {
  await expandedChanged(!expandedRows.value.includes(item.id), item);
}

async function refreshPreview() {
  if (!selectedRevoke.value) return;
  dangerErrorCode.value = '';
  if (selectedRevoke.value.kind === 'profile') {
    preview.value = await resourcesApi.createPreview({
      kind: 'subscription.revoke',
      target_id: selectedRevoke.value.subscription.profile_id,
      params: { profile_id: selectedRevoke.value.subscription.profile_id },
    });
    return;
  }
  preview.value = await resourcesApi.createPreview({
    kind: 'subscription.token_revoke',
    target_id: selectedRevoke.value.token.id,
    params: {
      subscription_id: selectedRevoke.value.subscription.id,
      token_id: selectedRevoke.value.token.id,
    },
  });
}

async function openTokenRevoke(subscription: Subscription, token: SubscriptionToken) {
  selectedRevoke.value = { kind: 'token', subscription, token };
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

async function openProfileRevoke(subscription: Subscription) {
  selectedRevoke.value = { kind: 'profile', subscription };
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
  if (!selectedRevoke.value) return;
  dangerBusy.value = true;
  dangerErrorCode.value = '';
  dangerErrorMessage.value = '';
  try {
    const target = selectedRevoke.value;
    if (target.kind === 'profile') {
      const accepted = await resourcesApi.forceRevoke(
        target.subscription.profile_id,
        { preview_id: payload.preview_id, confirmation: payload.confirmation },
        payload.idempotency_key,
      );
      dangerOpen.value = false;
      await router.push(`/operations/${accepted.operation_id}`);
    } else {
      await resourcesApi.revokeSubscriptionToken(
        target.subscription.id,
        target.token.id,
        { preview_id: payload.preview_id, confirmation: payload.confirmation },
        payload.idempotency_key,
      );
      dangerOpen.value = false;
      await loadTokens(target.subscription.id);
      await reload();
    }
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
  selectedRevoke.value = null;
  dangerErrorCode.value = '';
  dangerErrorMessage.value = '';
}
</script>

<template>
  <Page title="订阅池" description="统一订阅链接与 Token 生命周期">
    <template #title><h1 class="mb-2 text-lg font-semibold">订阅池</h1></template>
    <template #extra>
      <Space>
        <Button type="primary" @click="openEditor()"><template #icon><Plus :size="16" /></template>创建订阅</Button>
        <Button title="刷新" aria-label="刷新" @click="reload">
          <template #icon><RefreshCw :size="17" /></template>
        </Button>
      </Space>
    </template>
    <Input.Search v-model:value="search" class="mb-4 max-w-sm" placeholder="搜索 Token 对应的访问配置" allow-clear @search="searchSubscriptions" />
    <PageState :loading="loading" :error="error" :empty="false" @retry="reload">
      <Alert v-if="actionError" class="mb-4" type="error" show-icon :message="actionError" role="alert" />
      <Alert v-if="empty" class="mb-4" type="info" show-icon message="当前没有已签发的 Token。" />
      <Alert class="mb-4" type="info" show-icon message="所有 Token 集中在同一个订阅池。统一链接默认提供包含全部已发布协议的 Mihomo 配置；每个 Token 都可以单独撤销。" />
      <Card :bordered="false">
        <Table
          :columns="columns"
          :data-source="data?.items || []"
          row-key="id"
          :expanded-row-keys="expandedRows"
          :pagination="{current: page, pageSize: 25, total: data?.total || 0, showSizeChanger: false}"
          :scroll="{ x: 'max-content' }"
          @change="pageChanged"
          @expand="expandedChanged"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'profile_name'">
              <strong class="block font-medium">Token #{{ record.token_epoch }}</strong>
              <span class="block text-muted-foreground">{{ record.profile_name }}</span>
              <small class="text-muted-foreground">{{ record.id }}</small>
            </template>
            <StatusBadge v-else-if="column.key === 'status'" :value="record.current_token_status || record.status" />
            <template v-else-if="column.key === 'usage'">{{ usage(record as Subscription) }}</template>
            <Space v-else-if="column.key === 'node_counts' && record.node_counts" size="small" wrap>
              <span>已分配 {{ record.node_counts.assigned }} / {{ record.node_counts.expected }}</span>
              <span>健康 {{ record.node_counts.ready }}</span>
              <span>已发布 {{ record.node_counts.published }}</span>
              <Tag :color="record.node_counts.mismatch ? 'error' : 'success'">
                {{ record.node_counts.mismatch ? '节点不匹配' : '节点一致' }}
              </Tag>
            </Space>
            <span v-else-if="column.key === 'node_counts'" class="text-muted-foreground">未核对</span>
            <template v-else-if="column.key === 'current_revision'">{{ record.current_revision || '-' }}</template>
            <template v-else-if="column.key === 'formats'">{{ record.formats?.join(' / ') || '-' }}</template>
            <StatusBadge v-else-if="column.key === 'revision_usable'" :value="record.revision_usable" />
            <Space v-else-if="column.key === 'actions'" wrap>
              <Button type="link" @click="openEditor(record.id)"><template #icon><Settings :size="14" /></template>管理</Button>
              <Button type="link" :loading="tokenLoading[record.id]" @click="toggleTokens(record as Subscription)">
                <template #icon><KeyRound :size="14" /></template>
                Token 历史
              </Button>
              <Button type="link" :disabled="Boolean(busyAction) || record.status !== 'ACTIVE'" :loading="busyAction === `rotate:${record.id}`" @click="rotate(record as Subscription)">
                <template #icon><RotateCw :size="14" /></template>
                轮换 Token
              </Button>
              <Button type="link" :disabled="Boolean(busyAction) || record.status !== 'ACTIVE'" :loading="busyAction === `publish:${record.id}`" @click="publish(record as Subscription)">
                <template #icon><Send :size="14" /></template>
                发布
              </Button>
              <Button type="link" danger :disabled="Boolean(busyAction) || record.status !== 'ACTIVE'" @click="openProfileRevoke(record as Subscription)">
                <template #icon><ShieldX :size="14" /></template>
                强制撤销访问
              </Button>
            </Space>
          </template>
          <template #expandedRowRender="{ record }">
            <div class="space-y-3">
              <strong class="block">Token 历史</strong>
              <Table
                :columns="tokenColumns"
                :data-source="tokensFor(record.id)"
                :loading="tokenLoading[record.id]"
                row-key="id"
                :pagination="{current: tokenPages[record.id] || 1, pageSize: tokenResults[record.id]?.page_size || 25, total: tokenResults[record.id]?.total || 0, showSizeChanger: false, simple: true}"
                size="small"
                @change="(value) => tokenPageChanged(record.id, value.current || 1)"
              >
                <template #bodyCell="{ column, record: token }">
                  <template v-if="column.key === 'token_epoch'">
                    <span>Token #{{ token.token_epoch }}</span>
                    <StatusBadge v-if="token.is_current" class="ml-2" value="ACTIVE" />
                  </template>
                  <StatusBadge v-else-if="column.key === 'status'" :value="token.status" />
                  <template v-else-if="column.key === 'created_at'">{{ new Date(token.created_at).toLocaleString() }}</template>
                  <template v-else-if="column.key === 'revoked_at'">{{ token.revoked_at ? new Date(token.revoked_at).toLocaleString() : '-' }}</template>
                  <Button
                    v-else-if="column.key === 'actions' && token.status === 'ACTIVE'"
                    type="link"
                    danger
                    @click="openTokenRevoke(record as Subscription, token as SubscriptionToken)"
                  >
                    <template #icon><ShieldX :size="14" /></template>
                    撤销此 Token
                  </Button>
                  <span v-else-if="column.key === 'actions'" class="text-muted-foreground">-</span>
                </template>
              </Table>
            </div>
          </template>
        </Table>
      </Card>
      <section class="mt-6">
        <h2 class="mb-3 text-base font-semibold">待签发 Token</h2>
        <PageState :loading="profilesLoading" :error="profilesError" :empty="false" @retry="reloadProfiles">
          <Card :bordered="false">
            <Table
              :columns="profileColumns"
              :data-source="unissuedProfiles"
              row-key="id"
              :pagination="{current: profilePage, pageSize: profilesData?.page_size || 25, total: profilesData?.total || 0, showSizeChanger: false}"
              :scroll="{ x: 'max-content' }"
              @change="profilePageChanged"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'name'">
                  <strong class="block font-medium">{{ record.name }}</strong>
                  <small class="text-muted-foreground">{{ record.id }}</small>
                </template>
                <StatusBadge v-else-if="column.key === 'status'" :value="record.status" />
                <template v-else-if="column.key === 'credential_count'">{{ record.credential_count }}</template>
                <Button
                  v-else-if="column.key === 'actions' && !record.subscription_id"
                  type="link"
                  :disabled="Boolean(issuingProfileId) || record.status !== 'ACTIVE'"
                  :loading="issuingProfileId === record.id"
                  @click="issueProfile(record as AccessProfile)"
                >
                  <template #icon><KeyRound :size="14" /></template>
                  签发 Token
                </Button>
              </template>
            </Table>
          </Card>
        </PageState>
      </section>
    </PageState>
    <SubscriptionEditor :open="editorOpen" :subscription-id="editorId" @close="editorOpen = false" @saved="reload" @delivery="delivery = $event" />
    <DangerConfirm :open="dangerOpen" :title="revokeTitle" :description="revokeDescription" :preview="preview" :busy="dangerBusy" :error-code="dangerErrorCode" :error-message="dangerErrorMessage" @close="closeDanger" @refresh="refreshPreview" @confirm="confirmRevoke" />
    <SecretDelivery :open="Boolean(delivery)" :delivery="delivery" @close="delivery = null" />
  </Page>
</template>
