<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { Plus, RefreshCw, Trash2 } from 'lucide-vue-next';

import { Page } from '@vben/common-ui';

import {
  Alert, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table,
} from 'ant-design-vue';

import {
  resourcesApi,
  SUPPORTED_REGIONS,
  type NodePool,
  type NodePoolAllocation,
} from '@/api/resources';
import PageState from '@/components/PageState.vue';
import StatusBadge from '@/components/StatusBadge.vue';
import { useResource } from '@/composables/useResource';

const DEFAULT_REGION = 'ap-southeast-1';
const FormItem = Form.Item;
const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '地区分配', key: 'allocations' },
  { title: '总额度', dataIndex: 'quota', key: 'quota' },
  { title: '占用', dataIndex: 'used', key: 'used' },
  { title: '可用', dataIndex: 'available', key: 'available' },
  { title: '允许创建', dataIndex: 'allow_create', key: 'allow_create' },
  { title: '操作', key: 'actions' },
];

interface AllocationDraft {
  region: string;
  quota: number;
}

const { data, loading, error, reload } = useResource(resourcesApi.nodePools);
const open = ref(false);
const saving = ref(false);
const formError = ref('');
const form = reactive<{ name: string; allocations: AllocationDraft[] }>({
  name: '',
  allocations: [{ region: DEFAULT_REGION, quota: 3 }],
});
const empty = computed(() => !data.value?.items.length);
const regionOptions = computed(() => SUPPORTED_REGIONS.map((region) => ({
  label: region,
  value: region,
})));

function resetForm() {
  form.name = '';
  form.allocations.splice(0, form.allocations.length, {
    region: DEFAULT_REGION,
    quota: 3,
  });
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

function allocationLabel(allocation: NodePoolAllocation) {
  const used = allocation.used ?? 0;
  return `${allocation.region}：${used}/${allocation.quota}`;
}

function allocationSummary(item: NodePool) {
  if (item.allocations?.length) return item.allocations.map(allocationLabel).join('、');
  if (item.region) return `${item.region}：${item.used}/${item.quota}`;
  return '未配置';
}

async function createPool() {
  if (saving.value) return;
  const allocations = form.allocations.map((item) => ({
    region: item.region,
    quota: Number(item.quota),
  }));
  const regions = allocations.map((item) => item.region);
  if (
    !form.name.trim()
    || allocations.some((item) => !item.region || !Number.isInteger(item.quota) || item.quota < 1)
    || new Set(regions).size !== regions.length
  ) {
    formError.value = '请填写名称，并为每个预设地区配置大于 0 的唯一额度';
    return;
  }
  saving.value = true;
  formError.value = '';
  try {
    await resourcesApi.createNodePool({ name: form.name.trim(), allocations });
    resetForm();
    open.value = false;
    await reload();
  } catch (caught) {
    formError.value = caught instanceof Error ? caught.message : '创建失败';
  } finally {
    saving.value = false;
  }
}

async function toggle(item: NodePool) {
  try {
    await resourcesApi.updateNodePool(item.id, { allow_create: !item.allow_create });
    await reload();
  } catch (caught) {
    formError.value = caught instanceof Error ? caught.message : '保存失败';
  }
}
</script>

<template>
  <Page title="节点池" description="按预设地区分别分配节点额度">
    <template #title><h1 class="mb-2 text-lg font-semibold">节点池</h1></template>
    <template #extra>
      <Space>
        <Button title="刷新" aria-label="刷新" @click="reload">
          <template #icon><RefreshCw :size="16" /></template>
        </Button>
        <Button type="primary" @click="open = true">
          <template #icon><Plus :size="16" /></template>
          新建节点池
        </Button>
      </Space>
    </template>
    <Alert v-if="formError" class="mb-4" :message="formError" type="error" show-icon />
    <Card>
      <PageState
        :loading="loading"
        :error="error"
        :empty="empty"
        empty-text="暂无节点池"
        @retry="reload"
      >
        <Table :columns="columns" :data-source="data?.items || []" :pagination="false" :scroll="{ x: 'max-content' }" row-key="id">
          <template #bodyCell="{ column, record }">
            <div v-if="column.key === 'name'">
              <strong>{{ record.name }}</strong>
              <div class="text-xs text-muted-foreground">{{ record.id }}</div>
            </div>
            <div v-else-if="column.key === 'allocations'">{{ allocationSummary(record as NodePool) }}</div>
            <StatusBadge v-else-if="column.key === 'allow_create'" :value="record.allow_create" />
            <Button v-else-if="column.key === 'actions'" type="link" @click="toggle(record as NodePool)">
              {{ record.allow_create ? '暂停创建' : '恢复创建' }}
            </Button>
          </template>
        </Table>
      </PageState>
    </Card>
    <Modal v-model:open="open" title="新建节点池" :footer="null" @cancel="resetForm">
      <Form :model="form" layout="vertical" @finish="createPool">
        <Alert v-if="formError" class="mb-4" :message="formError" type="error" show-icon />
        <FormItem label="名称" name="name" :rules="[{ required: true, message: '请输入名称' }]">
          <Input v-model:value="form.name" />
        </FormItem>
        <FormItem label="地区分配" required>
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
        <Button type="primary" html-type="submit" :loading="saving" block>{{ saving ? '保存中' : '创建' }}</Button>
      </Form>
    </Modal>
  </Page>
</template>
