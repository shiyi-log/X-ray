<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { Eye, MapPin, Play, Plus, RefreshCw, RotateCw, Trash2 } from 'lucide-vue-next';

import { Page } from '@vben/common-ui';

import {
  Alert, Button, Card, Descriptions, Form, Input, Modal, Select, Space, Table,
} from 'ant-design-vue';

import {
  resourcesApi,
  type ActionPreview,
  type CloudAccount,
  type ManagedNode,
} from '@/api/resources';
import { ApiError } from '@/api/request';
import DangerConfirm from '@/components/DangerConfirm.vue';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const FormItem = Form.Item;
const DescriptionItem = Descriptions.Item;
const columns = [
  { title: '服务器', dataIndex: 'name', key: 'name' },
  { title: 'IP', key: 'ip' },
  { title: '运行状态', key: 'runtime_status' },
  { title: '流量统计', key: 'traffic' },
  { title: '操作', key: 'actions' },
];

const providerLabels: Record<string, string> = {
  aws_lightsail: 'AWS Lightsail',
  aliyun_swas: '阿里云 SWAS',
};
const knownRuntimeStates = new Set([
  'ACTIVE', 'CREATING', 'DELETED', 'DELETING', 'ERROR', 'FAILED', 'PENDING',
  'PRESENT', 'PROVISIONED', 'READY', 'REBOOTED', 'REBOOTING', 'RECONCILIATION',
  'RESERVED', 'RUNNING', 'SHUTTING_DOWN', 'STARTING', 'STOPPED', 'STOPPED_BY_USER', 'STOPPING',
  'TERMINATED', 'TERMINATING', 'UNKNOWN',
]);

function providerLabel(provider: string) {
  return providerLabels[provider] ?? provider;
}

function isIpv4(value: unknown): value is string {
  return typeof value === 'string'
    && /^(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$/.test(value);
}

function nodeIp(node: ManagedNode) {
  const addresses = (node.addresses ?? []).flatMap((entry) => {
    if (typeof entry === 'string') return isIpv4(entry) ? [entry] : [];
    if (entry.family !== undefined && entry.family !== 4) return [];
    return [entry.value, entry.address, entry.ip_address, entry.ip].filter(
      isIpv4,
    );
  });
  return [...new Set(addresses)].join(', ') || '-';
}

function formatBytes(value?: number) {
  if (!Number.isFinite(value) || value === undefined || value < 0) return '-';
  if (value < 1024) return `${value} B`;
  const units = ['KiB', 'MiB', 'GiB', 'TiB'];
  let amount = value / 1024;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  return `${amount.toFixed(2)} ${units[unit]}`;
}

function runtimeStatus(node: ManagedNode) {
  const rawState = node.raw_cloud_state?.trim();
  if (rawState) {
    const normalized = rawState.toUpperCase().replace(/[\s-]+/g, '_');
    if (normalized === 'ACTIVE') return 'RUNNING';
    return knownRuntimeStates.has(normalized) ? normalized : 'UNKNOWN';
  }
  if (node.desired_state === 'DELETED' || node.desired_state === 'STOPPED') {
    return node.desired_state;
  }
  const provisioningState = node.provisioning_state?.toUpperCase();
  return provisioningState && knownRuntimeStates.has(provisioningState) ? provisioningState : 'UNKNOWN';
}

function canManageInstance(node: ManagedNode) {
  return Boolean(node.external_id) && node.desired_state !== 'DELETED';
}

function trafficTotal(node: ManagedNode) {
  if (node.traffic_state !== 'COLLECTED') return '尚未采集';
  return formatBytes(node.traffic_total_bytes);
}

const router = useRouter();
const { data, loading, error, reload } = useResource(resourcesApi.nodes);
const open = ref(false);
const saving = ref(false);
const formError = ref('');
const actionError = ref('');
const busyAction = ref('');
const accounts = ref<CloudAccount[]>([]);
const form = reactive({ account_id: '', region: '', plan_id: '', image_id: '' });
const empty = computed(() => !data.value?.items.length);
const accountOptions = computed(() => accounts.value.map((item) => ({
  label: item.name,
  value: item.id,
})));
const capabilities = ref<{ status: string; regions: string[] }[]>([]);
const regionAllocations = ref<{ region: string; available: number }[]>([]);
const loadingRegions = ref(false);
const regionOptions = computed(() => {
  const supported = new Set(
    capabilities.value
      .filter((item) => item.status === 'SUPPORTED')
      .flatMap((item) => item.regions),
  );
  return regionAllocations.value
    .filter((allocation) => supported.has(allocation.region))
    .map((allocation) => ({
      label: `${allocation.region}（可用 ${allocation.available}）`,
      value: allocation.region,
      disabled: allocation.available < 1,
    }));
});

const detailOpen = ref(false);
const detailLoading = ref(false);
const detailError = ref('');
const selectedNode = ref<ManagedNode | null>(null);
const dangerOpen = ref(false);
const dangerBusy = ref(false);
const dangerErrorCode = ref('');
const dangerErrorMessage = ref('');
const deletePreview = ref<ActionPreview | null>(null);

async function openCreate() {
  open.value = true;
  formError.value = '';
  form.account_id = '';
  form.region = '';
  form.plan_id = '';
  form.image_id = '';
  capabilities.value = [];
  try {
    const page = await resourcesApi.cloudAccounts();
    accounts.value = page.items.filter((item) => item.enabled);
  } catch (caught) {
    formError.value = caught instanceof Error ? caught.message : '云账号加载失败';
  }
}

async function accountChanged(value: unknown) {
  const accountId = typeof value === 'string' ? value : '';
  form.region = '';
  capabilities.value = [];
  regionAllocations.value = [];
  if (!accountId) return;
  loadingRegions.value = true;
  formError.value = '';
  try {
    const [result, pools] = await Promise.all([
      resourcesApi.capabilities(accountId),
      resourcesApi.nodePools(),
    ]);
    capabilities.value = result.items;
    const pool = pools.items[0];
    regionAllocations.value = (pool?.allocations?.length
      ? pool.allocations
      : pool ? [{ region: pool.region, quota: pool.quota, used: pool.used, available: pool.available }] : [])
      .map((allocation) => ({
        region: allocation.region,
        available: allocation.available ?? Math.max(allocation.quota - (allocation.used ?? 0), 0),
      }));
  } catch (caught) {
    formError.value = caught instanceof Error ? caught.message : '地区加载失败';
  } finally {
    loadingRegions.value = false;
  }
}

async function createNode() {
  if (saving.value) return;
  if (!regionOptions.value.some((option) => option.value === form.region && !option.disabled)) {
    formError.value = '所选地区未分配或已无可用额度';
    return;
  }
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

async function submitNodeAction(node: ManagedNode, action: 'start' | 'reboot') {
  if (busyAction.value) return;
  actionError.value = '';
  busyAction.value = `${action}:${node.id}`;
  try {
    const accepted = await resourcesApi.nodeAction(node.id, action);
    await router.push(`/operations/${accepted.operation_id}`);
  } catch (caught) {
    actionError.value = caught instanceof ApiError && caught.code === 'STEP_UP_REQUIRED'
      ? '近期身份验证已过期。请退出并重新完成密码与 MFA 验证后再次操作。'
      : caught instanceof Error ? caught.message : '操作提交失败';
  } finally {
    busyAction.value = '';
  }
}

async function openDetails(node: ManagedNode) {
  selectedNode.value = node;
  detailOpen.value = true;
  detailLoading.value = true;
  detailError.value = '';
  try {
    selectedNode.value = await resourcesApi.nodeDetail(node.id);
  } catch (caught) {
    detailError.value = caught instanceof Error ? caught.message : '服务器详情加载失败';
  } finally {
    detailLoading.value = false;
  }
}

async function refreshDeletePreview() {
  if (!selectedNode.value) return;
  dangerErrorCode.value = '';
  dangerErrorMessage.value = '';
  try {
    deletePreview.value = await resourcesApi.createPreview({
      kind: 'node.delete',
      target_id: selectedNode.value.id,
      params: {},
    });
  } catch (caught) {
    deletePreview.value = null;
    if (caught instanceof ApiError) dangerErrorCode.value = caught.code;
    dangerErrorMessage.value = caught instanceof Error ? caught.message : '删除预览失败';
  }
}

async function openDelete(node: ManagedNode) {
  selectedNode.value = node;
  deletePreview.value = null;
  dangerOpen.value = true;
  dangerErrorCode.value = '';
  dangerErrorMessage.value = '';
  await refreshDeletePreview();
}

async function confirmDelete(payload: {
  preview_id: string;
  confirmation: string;
  idempotency_key: string;
}) {
  if (!selectedNode.value) return;
  dangerBusy.value = true;
  dangerErrorCode.value = '';
  dangerErrorMessage.value = '';
  try {
    const accepted = await resourcesApi.nodeAction(
      selectedNode.value.id,
      'delete',
      { preview_id: payload.preview_id, confirmation: payload.confirmation },
      payload.idempotency_key,
    );
    dangerOpen.value = false;
    await router.push(`/operations/${accepted.operation_id}`);
  } catch (caught) {
    if (caught instanceof ApiError) {
      dangerErrorCode.value = caught.code;
      if (caught.status === 409 && caught.code !== 'STEP_UP_REQUIRED') {
        dangerErrorMessage.value = '预览已失效，正在刷新。请重新核对后再次确认。';
        await refreshDeletePreview();
      } else {
        dangerErrorMessage.value = caught.message;
      }
    } else {
      dangerErrorMessage.value = caught instanceof Error ? caught.message : '删除操作提交失败';
    }
  } finally {
    dangerBusy.value = false;
  }
}

function closeDelete() {
  dangerOpen.value = false;
  deletePreview.value = null;
  selectedNode.value = null;
  dangerErrorCode.value = '';
  dangerErrorMessage.value = '';
}
</script>

<template>
  <Page title="服务器管理" description="服务器状态、流量与操作">
    <template #title><h1 class="mb-2 text-lg font-semibold">服务器管理</h1></template>
    <template #extra>
      <Space>
        <Button title="刷新" aria-label="刷新" @click="reload">
          <template #icon><RefreshCw :size="16" /></template>
        </Button>
        <Button title="地区额度" aria-label="地区" @click="router.push('/node-pools')">
          <template #icon><MapPin :size="16" /></template>
          地区
        </Button>
        <Button type="primary" @click="openCreate">
          <template #icon><Plus :size="16" /></template>
          创建服务器
        </Button>
      </Space>
    </template>
    <Alert v-if="actionError" class="mb-4" type="error" show-icon :message="actionError" role="alert" />
    <Card>
      <PageState :loading="loading" :error="error" :empty="empty" empty-text="暂无服务器" @retry="reload">
        <Table :columns="columns" :data-source="data?.items || []" :pagination="false" :scroll="{ x: 'max-content' }" row-key="id">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'name'">
              <strong>{{ record.name }}</strong>
              <div class="text-xs text-muted-foreground">{{ providerLabel(record.provider) }} · {{ record.region }}</div>
            </template>
            <span v-else-if="column.key === 'ip'">{{ nodeIp(record as ManagedNode) }}</span>
            <StatusBadge v-else-if="column.key === 'runtime_status'" :value="runtimeStatus(record as ManagedNode)" />
            <div v-else-if="column.key === 'traffic'" :title="record.traffic_sampled_at || undefined">
              <strong>{{ trafficTotal(record as ManagedNode) }}</strong>
              <div v-if="record.traffic_state === 'COLLECTED'" class="text-xs text-muted-foreground">
                上行 {{ formatBytes(record.traffic_upload_bytes) }} · 下行 {{ formatBytes(record.traffic_download_bytes) }}
              </div>
            </div>
            <Space v-else-if="column.key === 'actions'" wrap size="small">
              <Button type="link" :disabled="Boolean(busyAction) || !canManageInstance(record as ManagedNode)" :title="canManageInstance(record as ManagedNode) ? '启动服务器' : '服务器尚无可操作的云实例'" :loading="busyAction === `start:${record.id}`" @click="submitNodeAction(record as ManagedNode, 'start')">
                <template #icon><Play :size="14" /></template>
                启动
              </Button>
              <Button type="link" :disabled="Boolean(busyAction) || !canManageInstance(record as ManagedNode)" :title="canManageInstance(record as ManagedNode) ? '重启服务器' : '服务器尚无可操作的云实例'" :loading="busyAction === `reboot:${record.id}`" @click="submitNodeAction(record as ManagedNode, 'reboot')">
                <template #icon><RotateCw :size="14" /></template>
                重启
              </Button>
              <Button type="link" :disabled="Boolean(busyAction)" @click="openDetails(record as ManagedNode)">
                <template #icon><Eye :size="14" /></template>
                详情
              </Button>
              <Button type="link" danger :disabled="Boolean(busyAction) || dangerBusy || !canManageInstance(record as ManagedNode)" :title="canManageInstance(record as ManagedNode) ? '删除服务器' : '服务器尚无可操作的云实例'" @click="openDelete(record as ManagedNode)">
                <template #icon><Trash2 :size="14" /></template>
                删除
              </Button>
            </Space>
          </template>
        </Table>
      </PageState>
    </Card>

    <Modal v-model:open="open" title="创建服务器" :footer="null" :after-close="() => { form.region = ''; }">
      <Form :model="form" layout="vertical" @finish="createNode">
        <Alert v-if="formError" class="mb-4" :message="formError" type="error" show-icon />
        <FormItem label="云账号" name="account_id" :rules="[{ required: true, message: '请选择云账号' }]">
          <Select v-model:value="form.account_id" :options="accountOptions" aria-label="云账号" placeholder="请选择" @change="accountChanged" />
        </FormItem>
        <FormItem label="地区" name="region" :rules="[{ required: true, message: '请选择地区' }]">
          <Select v-model:value="form.region" :options="regionOptions" aria-label="地区" :loading="loadingRegions" :disabled="!form.account_id" placeholder="请选择" />
        </FormItem>
        <FormItem label="套餐 ID" name="plan_id" :rules="[{ required: true, message: '请输入套餐 ID' }]">
          <Input v-model:value="form.plan_id" aria-label="套餐 ID" />
        </FormItem>
        <FormItem label="镜像 ID" name="image_id" :rules="[{ required: true, message: '请输入镜像 ID' }]">
          <Input v-model:value="form.image_id" aria-label="镜像 ID" />
        </FormItem>
        <Button type="primary" html-type="submit" :loading="saving" block>{{ saving ? '提交中' : '提交创建操作' }}</Button>
      </Form>
    </Modal>

    <Modal v-model:open="detailOpen" title="服务器详情" :footer="null">
      <PageState :loading="detailLoading" :error="detailError || undefined" @retry="selectedNode && openDetails(selectedNode)">
        <Descriptions v-if="selectedNode" bordered :column="1">
          <DescriptionItem label="服务器">{{ selectedNode.name }}</DescriptionItem>
          <DescriptionItem label="IP">{{ nodeIp(selectedNode) }}</DescriptionItem>
          <DescriptionItem label="平台">{{ providerLabel(selectedNode.provider) }}</DescriptionItem>
          <DescriptionItem label="地区">{{ selectedNode.region }}</DescriptionItem>
          <DescriptionItem label="运行状态"><StatusBadge :value="runtimeStatus(selectedNode)" /></DescriptionItem>
          <DescriptionItem label="健康状态"><StatusBadge :value="selectedNode.health_state" /></DescriptionItem>
          <DescriptionItem label="安全状态"><StatusBadge :value="selectedNode.security_state" /></DescriptionItem>
          <DescriptionItem label="流量统计">
            {{ trafficTotal(selectedNode) }}
            <span v-if="selectedNode.traffic_state === 'COLLECTED'">
              （上行 {{ formatBytes(selectedNode.traffic_upload_bytes) }}，下行 {{ formatBytes(selectedNode.traffic_download_bytes) }}）
            </span>
          </DescriptionItem>
        </Descriptions>
      </PageState>
    </Modal>

    <DangerConfirm
      :open="dangerOpen"
      :preview="deletePreview"
      :busy="dangerBusy"
      :error-code="dangerErrorCode"
      :error-message="dangerErrorMessage"
      title="确认删除服务器"
      description="删除操作会作用于当前服务器，并在操作中心显示执行结果。"
      @close="closeDelete"
      @refresh="refreshDeletePreview"
      @confirm="confirmDelete"
    />
  </Page>
</template>
