<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { Plus, RefreshCw, Trash2 } from 'lucide-vue-next';

import { Page } from '@vben/common-ui';

import {
  Alert, Button, Card, Form, InputNumber, Modal, Select, Space, Switch, Table,
} from 'ant-design-vue';

import {
  resourcesApi,
  SUPPORTED_REGIONS,
  type NodePool,
} from '@/api/resources';
import PageState from '@/components/PageState.vue';
import { useResource } from '@/composables/useResource';

const DEFAULT_REGION = 'ap-southeast-1';
const FormItem = Form.Item;
const columns = [
  { title: 'IP', dataIndex: 'name', key: 'name' },
  { title: '地区', key: 'allocations' },
  { title: '允许创建', key: 'allow_create' },
];

interface AllocationDraft {
  region: string;
  quota: number;
}

const { data, loading, error, reload } = useResource(resourcesApi.nodePools);
const open = ref(false);
const saving = ref(false);
const formError = ref('');
const editingPoolId = ref<string | null>(null);
const form = reactive<{ allocations: AllocationDraft[]; allowCreate: boolean }>({
  allocations: [{ region: DEFAULT_REGION, quota: 3 }],
  allowCreate: true,
});
const empty = computed(() => !data.value?.items.length);
const regionOptions = computed(() => {
  const configured = data.value?.items[0];
  const configuredRegions = configured?.allocations?.map((item) => item.region)
    ?? (configured?.region ? [configured.region] : []);
  const supported = new Set<string>(SUPPORTED_REGIONS);
  const historicalRegions = [...new Set(configuredRegions)]
    .filter((region) => !supported.has(region));
  return [
    ...SUPPORTED_REGIONS.map((region) => ({ label: region, value: region })),
    ...historicalRegions.map((region) => ({
      label: `${region}（历史地区）`,
      value: region,
    })),
  ];
});

function resetForm() {
  editingPoolId.value = null;
  form.allocations.splice(0, form.allocations.length, {
    region: DEFAULT_REGION,
    quota: 3,
  });
  form.allowCreate = true;
}

function openEditor() {
  formError.value = '';
  const existing = data.value?.items[0];
  editingPoolId.value = existing?.id ?? null;
  if (existing) {
    form.allowCreate = existing.allow_create ?? true;
    const allocations = existing.allocations?.length
      ? existing.allocations
      : [{ region: existing.region, quota: existing.quota }];
    form.allocations.splice(
      0,
      form.allocations.length,
      ...allocations.map((item) => ({ region: item.region, quota: item.quota })),
    );
  } else {
    resetForm();
  }
  open.value = true;
}

function addAllocation() {
  const selected = new Set(form.allocations.map((item) => item.region));
  const region = SUPPORTED_REGIONS.find((item) => !selected.has(item)) || '';
  form.allocations.push({ region, quota: 1 });
}

function removeAllocation(index: number) {
  if (form.allocations.length > 1) form.allocations.splice(index, 1);
}

function optionsFor(index: number) {
  const selectedByOtherRows = new Set(
    form.allocations.filter((_, rowIndex) => rowIndex !== index).map((item) => item.region),
  );
  return regionOptions.value.map((option) => ({
    ...option,
    disabled: selectedByOtherRows.has(option.value),
  }));
}

function regionSummary(item: NodePool) {
  const regions = item.allocations?.map((allocation) => allocation.region) ?? item.regions;
  return regions?.length ? regions.join('、') : item.region || '未配置';
}

async function createPool() {
  if (saving.value) return;
  const allocations = form.allocations.map((item) => ({
    region: item.region,
    quota: Number(item.quota),
  }));
  const regions = allocations.map((item) => item.region);
  if (
    allocations.some((item) => !item.region || !Number.isInteger(item.quota) || item.quota < 1)
    || new Set(regions).size !== regions.length
  ) {
    formError.value = '请为每个预设地区配置大于 0 的唯一额度';
    return;
  }
  saving.value = true;
  formError.value = '';
  try {
    if (editingPoolId.value) {
      await resourcesApi.updateNodePool(editingPoolId.value, {
        allocations,
        allow_create: form.allowCreate,
      });
    } else {
      await resourcesApi.createNodePool({ allocations, allow_create: form.allowCreate });
    }
    resetForm();
    open.value = false;
    await reload();
  } catch (caught) {
    formError.value = caught instanceof Error ? caught.message : '保存失败';
  } finally {
    saving.value = false;
  }
}

</script>

<template>
  <Page title="地区" description="管理服务器创建地区配置">
    <template #title><h1 class="mb-2 text-lg font-semibold">地区</h1></template>
    <template #extra>
      <Space>
        <Button title="刷新" aria-label="刷新" @click="reload">
          <template #icon><RefreshCw :size="16" /></template>
        </Button>
        <Button type="primary" @click="openEditor">
          <template #icon><Plus :size="16" /></template>
          地区分配
        </Button>
      </Space>
    </template>
    <Alert v-if="formError" class="mb-4" :message="formError" type="error" show-icon />
    <Card>
      <PageState
        :loading="loading"
        :error="error"
        :empty="empty"
        empty-text="暂无地区配置"
        @retry="reload"
      >
        <Table :columns="columns" :data-source="data?.items || []" :pagination="false" :scroll="{ x: 'max-content' }" row-key="id">
          <template #bodyCell="{ column, record }">
            <div v-if="column.key === 'name'">
              <strong>{{ record.name }}</strong>
              <div class="text-xs text-muted-foreground">{{ record.id }}</div>
            </div>
            <div v-else-if="column.key === 'allocations'">{{ regionSummary(record as NodePool) }}</div>
            <span v-else-if="column.key === 'allow_create'">
              {{ (record as NodePool).allow_create ?? true ? '允许' : '已关闭' }}
            </span>
          </template>
        </Table>
      </PageState>
    </Card>
    <Modal v-model:open="open" title="地区分配" :footer="null" @cancel="resetForm">
      <Form :model="form" layout="vertical" @finish="createPool">
        <Alert v-if="formError" class="mb-4" :message="formError" type="error" show-icon />
        <FormItem label="地区" required>
          <div v-for="(allocation, index) in form.allocations" :key="index" class="mb-2 flex items-center gap-2">
            <Select
              v-model:value="allocation.region"
              class="flex-1"
              :options="optionsFor(index)"
              placeholder="选择预设地区"
            />
            <InputNumber
              v-model:value="allocation.quota"
              :min="1"
              :precision="0"
              class="w-28"
              placeholder="数量"
            />
            <Button
              type="text"
              danger
              :disabled="form.allocations.length === 1"
              aria-label="移除地区"
              @click="removeAllocation(index)"
            >
              <template #icon><Trash2 :size="16" /></template>
            </Button>
          </div>
          <Button type="dashed" block :disabled="form.allocations.length >= SUPPORTED_REGIONS.length" @click="addAllocation">
            <template #icon><Plus :size="16" /></template>
            添加地区
          </Button>
        </FormItem>
        <FormItem label="允许创建服务器">
          <Space>
            <Switch
              v-model:checked="form.allowCreate"
              aria-label="允许创建服务器"
              checked-children="开"
              un-checked-children="关"
            />
            <span>{{ form.allowCreate ? '新服务器可按地区额度创建' : '已禁止创建新服务器' }}</span>
          </Space>
        </FormItem>
        <Alert
          v-if="!form.allowCreate"
          class="mb-4"
          type="warning"
          show-icon
          message="关闭后，服务端会拒绝新的服务器创建；现有服务器不受影响。"
        />
        <Button type="primary" html-type="submit" :loading="saving" block>{{ saving ? '保存中' : '保存' }}</Button>
      </Form>
    </Modal>
  </Page>
</template>
