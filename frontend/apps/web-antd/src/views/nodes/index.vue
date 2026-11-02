<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { Eye, MapPin, Play, Plus, RefreshCw, RotateCw, Trash2 } from 'lucide-vue-next';

import { Page } from '@vben/common-ui';

import {
  Alert, Button, Card, Descriptions, Form, Input, Modal, Select, Space, Switch, Table,
} from 'ant-design-vue';

import {
  resourcesApi,
  regionLabel,
  type ActionPreview,
  type CloudAccount,
  type ManagedNode,
  type NodePool,
} from '@/api/resources';
import { ApiError } from '@/api/request';
import DangerConfirm from '@/components/DangerConfirm.vue';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';
import NodePoolAllocationEditor from '@/views/node-pools/NodePoolAllocationEditor.vue';

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
  'NOT_FOUND', 'UNVERIFIED',
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
  if (node.observation_error === 'RESOURCE_NOT_FOUND') return 'NOT_FOUND';
  if (node.observation_error) return 'UNVERIFIED';
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
const allocationOpen = ref(false);
const allocationLoading = ref(false);
const allocationPool = ref<NodePool | null>(null);
const allocationError = ref('');
const saving = ref(false);
const formError = ref('');
const actionError = ref('');
const statusRefreshNotice = ref('');
const statusRefreshError = ref('');
const statusRefreshing = ref(false);
const includeMissingNodes = ref(false);
const busyAction = ref('');
const accounts = ref<CloudAccount[]>([]);
const form = reactive({ account_id: '', region: '', plan_id: '', image_id: '' });
const missingNodeCount = computed(() => data.value?.items.filter(
  (item) => item.observation_error === 'RESOURCE_NOT_FOUND',
).length ?? 0);
const visibleNodes = computed(() => (data.value?.items ?? []).filter(
  (item) => includeMissingNodes.value || item.observation_error !== 'RESOURCE_NOT_FOUND',
));
const empty = computed(() => !visibleNodes.value.length);
const emptyText = computed(() => missingNodeCount.value && !includeMissingNodes.value
  ? '云端已确认不存在的服务器已隐藏'
  : '暂无服务器');
const accountOptions = computed(() => accounts.value.map((item) => ({
  label: item.enabled ? item.name : `${item.name}（已停用）`,
  value: item.id,
  disabled: !item.enabled,
})));
const capabilities = ref<{ name: string; status: string; regions: string[]; reason?: string }[]>([]);
const regionAllocations = ref<{ region: string; available: number }[]>([]);
const loadingRegions = ref(false);
const poolGateState = ref<'loading' | 'ready' | 'disabled' | 'unconfigured'>('loading');
const regionOptions = computed(() => {
  return regionAllocations.value
    .map((allocation) => {
      const matchingCapabilities = capabilities.value.filter((item) =>
        item.regions.includes(allocation.region),
      );
      const supported = matchingCapabilities.some((item) => item.status === 'SUPPORTED');
      let reason = '';
      if (!supported) {
        reason = matchingCapabilities.some((item) => item.status === 'UNVERIFIED')
          ? '能力未验证'
          : matchingCapabilities.length ? '云厂商不支持' : '能力未登记';
      } else if (allocation.available < 1) {
        reason = '额度已用完';
      }
      return {
        label: `${regionLabel(allocation.region)}（${reason || `可用 ${allocation.available}`}）`,
        value: allocation.region,
        disabled: !supported || allocation.available < 1,
        reason,
      };
    });
});
const blockedCapabilitySummaries = computed(() => capabilities.value
  .filter((item) => item.status !== 'SUPPORTED')
  .map((item) => `${item.name}：${item.status === 'UNVERIFIED' ? '未验证' : '不支持'}${item.reason ? `，${item.reason}` : ''}`));

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
  regionAllocations.value = [];
  poolGateState.value = 'loading';
  try {
    const [page, pools] = await Promise.all([
      resourcesApi.cloudAccounts(),
      resourcesApi.nodePools(),
    ]);
    accounts.value = page.items;
    const pool = pools.items[0];
    if (!pool) {
      poolGateState.value = 'unconfigured';
      return;
    }
    poolGateState.value = pool.allow_create === false ? 'disabled' : 'ready';
    regionAllocations.value = (pool.allocations?.length
      ? pool.allocations
      : [{ region: pool.region, quota: pool.quota, used: pool.used, available: pool.available }])
      .map((allocation) => ({
        region: allocation.region,
        available: allocation.available ?? Math.max(allocation.quota - (allocation.used ?? 0), 0),
      }));
  } catch (caught) {
    formError.value = caught instanceof Error ? caught.message : '云账号加载失败';
    poolGateState.value = 'unconfigured';
  }
}

async function openAllocationEditor() {
  open.value = false;
  allocationLoading.value = true;
  allocationError.value = '';
  try {
    const page = await resourcesApi.nodePools();
    allocationPool.value = page.items[0] ?? null;
    allocationOpen.value = true;
  } catch (caught) {
    allocationError.value = caught instanceof Error ? caught.message : '地区分配加载失败';
  } finally {
    allocationLoading.value = false;
  }
}

async function allocationSaved() {
  try {
    const page = await resourcesApi.nodePools();
    allocationPool.value = page.items[0] ?? null;
  } catch {
    allocationError.value = '地区额度已保存，重新读取配置失败';
  }
}

async function refreshCloudStatuses() {
  if (statusRefreshing.value) return;
  statusRefreshNotice.value = '';
  statusRefreshError.value = '';
  statusRefreshing.value = true;
  try {
    const firstPage = await resourcesApi.nodes(1, 100);
    const allNodes = [...firstPage.items];
    const pageCount = Math.ceil(firstPage.total / firstPage.page_size);
    for (let page = 2; page <= pageCount; page += 1) {
      const nextPage = await resourcesApi.nodes(page, 100);
      allNodes.push(...nextPage.items);
    }
    const targets = allNodes.filter(
      (node) => Boolean(node.external_id) && node.desired_state !== 'DELETED',
    );
    if (!targets.length) {
      statusRefreshNotice.value = '没有可检查的云端服务器';
      return;
    }
    const results = await Promise.allSettled(
      targets.map((node) => resourcesApi.refreshNodeStatus(node.id)),
    );
    const accepted = results.filter((result) => result.status === 'fulfilled').length;
    const failed = results.length - accepted;
    if (failed) {
      statusRefreshError.value = `${accepted} 台已提交，${failed} 台提交失败`;
    } else {
      statusRefreshNotice.value = `已提交 ${accepted} 台服务器的云端状态更新；操作完成后刷新列表查看，进度可在操作中心查看`;
    }
  } catch (caught) {
    statusRefreshError.value = caught instanceof Error ? caught.message : '读取服务器列表失败';
  } finally {
    statusRefreshing.value = false;
  }
}

async function accountChanged(value: unknown) {
  const accountId = typeof value === 'string' ? value : '';
  form.region = '';
  capabilities.value = [];
  if (!accountId) return;
  const selectedAccount = accounts.value.find((item) => item.id === accountId);
  if (!selectedAccount?.enabled) {
    formError.value = '所选云账号已停用，请在云账号页面启用后再创建服务器';
    return;
  }
  loadingRegions.value = true;
  formError.value = '';
  try {
    const result = await resourcesApi.capabilities(accountId);
    capabilities.value = result.items;
  } catch (caught) {
    formError.value = caught instanceof Error ? caught.message : '地区加载失败';
  } finally {
    loadingRegions.value = false;
  }
}

async function createNode() {
  if (saving.value) return;
  if (poolGateState.value === 'disabled') {
    formError.value = '地区设置已禁止创建服务器，请先调整地区设置';
    return;
  }
  if (poolGateState.value !== 'ready') {
    formError.value = '尚未配置地区额度，请先完成地区分配';
    return;
  }
  const selectedRegion = regionOptions.value.find((option) => option.value === form.region);
  if (!selectedRegion || selectedRegion.disabled) {
    formError.value = selectedRegion?.reason
      ? `${form.region} 暂不可创建：${selectedRegion.reason}`
      : '所选地区未分配或已无可用额度';
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
        <Button title="刷新列表" aria-label="刷新列表" @click="reload">
          <template #icon><RefreshCw :size="16" /></template>
        </Button>
        <Button :loading="statusRefreshing" @click="refreshCloudStatuses">
          <template #icon><RotateCw :size="16" /></template>
          更新状态
        </Button>
        <Button :loading="allocationLoading" @click="openAllocationEditor">
          <template #icon><MapPin :size="16" /></template>
          地区分配
        </Button>
        <Button type="primary" @click="openCreate">
          <template #icon><Plus :size="16" /></template>
          创建服务器
        </Button>
        <Space v-if="missingNodeCount" size="small">
          <Switch v-model:checked="includeMissingNodes" aria-label="显示已不存在服务器" />
          <span>显示已不存在</span>
        </Space>
      </Space>
    </template>
    <Alert v-if="actionError" class="mb-4" type="error" show-icon :message="actionError" role="alert" />
    <Alert v-if="allocationError" class="mb-4" type="error" show-icon :message="allocationError" />
    <Alert v-if="statusRefreshNotice" class="mb-4" type="info" show-icon :message="statusRefreshNotice" />
    <Alert v-if="statusRefreshError" class="mb-4" type="warning" show-icon :message="statusRefreshError" />
    <Card>
      <PageState :loading="loading" :error="error" :empty="empty" :empty-text="emptyText" @retry="reload">
        <Table :columns="columns" :data-source="visibleNodes" :pagination="false" :scroll="{ x: 'max-content' }" row-key="id">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'name'">
              <strong>{{ record.name }}</strong>
              <div class="text-xs text-muted-foreground">{{ providerLabel(record.provider) }} · {{ regionLabel(record.region) }}</div>
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
        <Alert
          v-if="poolGateState === 'disabled'"
          class="mb-4"
          type="warning"
          show-icon
          message="已禁止创建新服务器"
          description="现有服务器不受影响。请在地区设置中重新允许创建。"
        />
        <Alert
          v-else-if="poolGateState === 'unconfigured'"
          class="mb-4"
          type="info"
          show-icon
          message="尚未配置地区额度"
          description="创建服务器前，需要先在地区设置中分配额度。"
        />
        <Button
          v-if="poolGateState === 'disabled' || poolGateState === 'unconfigured'"
          class="mb-4"
          type="link"
          @click="openAllocationEditor"
        >
          打开地区分配
        </Button>
        <FormItem label="云账号" name="account_id" :rules="[{ required: true, message: '请选择云账号' }]">
          <Select v-model:value="form.account_id" :options="accountOptions" aria-label="云账号" :loading="poolGateState === 'loading'" placeholder="请选择" @change="accountChanged" />
        </FormItem>
        <Alert
          v-if="accounts.length && !accounts.some((item) => item.enabled)"
          class="mb-4"
          type="warning"
          show-icon
          message="没有已启用的云账号"
          description="请在云账号页面启用一个账号后再创建服务器。"
        />
        <FormItem label="地区" name="region" :rules="[{ required: true, message: '请选择地区' }]">
          <Select v-model:value="form.region" :options="regionOptions" aria-label="地区" :loading="loadingRegions" :disabled="!form.account_id" placeholder="请选择" />
        </FormItem>
        <Alert
          v-if="blockedCapabilitySummaries.length"
          class="mb-4"
          type="info"
          show-icon
          message="部分云能力尚不可用"
          :description="blockedCapabilitySummaries.join('；')"
        />
        <FormItem label="套餐 ID" name="plan_id" :rules="[{ required: true, message: '请输入套餐 ID' }]">
          <Input v-model:value="form.plan_id" aria-label="套餐 ID" />
        </FormItem>
        <FormItem label="镜像 ID" name="image_id" :rules="[{ required: true, message: '请输入镜像 ID' }]">
          <Input v-model:value="form.image_id" aria-label="镜像 ID" />
        </FormItem>
        <Button type="primary" html-type="submit" :loading="saving" :disabled="poolGateState !== 'ready'" block>{{ saving ? '提交中' : '提交创建操作' }}</Button>
      </Form>
    </Modal>

    <NodePoolAllocationEditor
      v-model:open="allocationOpen"
      :pool="allocationPool"
      @saved="allocationSaved"
    />

    <Modal v-model:open="detailOpen" title="服务器详情" :footer="null">
      <PageState :loading="detailLoading" :error="detailError || undefined" @retry="selectedNode && openDetails(selectedNode)">
        <Descriptions v-if="selectedNode" bordered :column="1">
          <DescriptionItem label="服务器">{{ selectedNode.name }}</DescriptionItem>
          <DescriptionItem label="IP">{{ nodeIp(selectedNode) }}</DescriptionItem>
          <DescriptionItem label="平台">{{ providerLabel(selectedNode.provider) }}</DescriptionItem>
          <DescriptionItem label="地区">{{ regionLabel(selectedNode.region) }}</DescriptionItem>
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
