<script setup lang="ts">
import { reactive, ref, watch } from 'vue';
import { Alert, Button, Form, InputNumber, Modal, Space, Switch } from 'ant-design-vue';

import { resourcesApi, SUPPORTED_REGIONS, type NodePool } from '@/api/resources';

const props = defineProps<{ open: boolean; pool: NodePool | null }>();
const emit = defineEmits<{
  'update:open': [value: boolean];
  saved: [];
}>();

const FormItem = Form.Item;
interface AllocationDraft {
  region: string;
  quota: number;
  historical?: boolean;
}

const form = reactive<{ allocations: AllocationDraft[]; allowCreate: boolean }>({
  allocations: [],
  allowCreate: true,
});
const saving = ref(false);
const error = ref('');

function seedForm(pool: NodePool | null) {
  const configured = pool?.allocations?.length
    ? pool.allocations
    : pool ? [{ region: pool.region, quota: pool.quota }] : [];
  const configuredByRegion = new Map(configured.map((item) => [item.region, item.quota]));
  const supported = new Set<string>(SUPPORTED_REGIONS);
  const allocations = [
    ...SUPPORTED_REGIONS.map((region) => ({
      region,
      quota: configuredByRegion.get(region) ?? 0,
    })),
    ...configured
      .filter((item) => !supported.has(item.region))
      .map((item) => ({ region: item.region, quota: item.quota, historical: true })),
  ];
  form.allocations.splice(0, form.allocations.length, ...allocations);
  form.allowCreate = pool?.allow_create ?? true;
  error.value = '';
}

watch(() => props.open, (open) => {
  if (open) seedForm(props.pool);
  else error.value = '';
});

async function save() {
  if (saving.value) return;
  const allocations = form.allocations.map(({ region, quota }) => ({
    region,
    quota: Number(quota),
  }));
  if (
    allocations.some((item) => !Number.isInteger(item.quota) || item.quota < 0)
    || new Set(allocations.map((item) => item.region)).size !== allocations.length
  ) {
    error.value = '请为每个地区填写唯一的非负整数额度';
    return;
  }
  saving.value = true;
  error.value = '';
  try {
    if (props.pool?.id) {
      await resourcesApi.updateNodePool(props.pool.id, {
        allocations,
        allow_create: form.allowCreate,
      });
    } else {
      await resourcesApi.createNodePool({
        allocations,
        allow_create: form.allowCreate,
      });
    }
    emit('update:open', false);
    emit('saved');
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '保存失败';
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Modal :open="props.open" title="地区分配" :footer="null" @cancel="emit('update:open', false)">
    <Form :model="form" layout="vertical" @finish="save">
      <Alert v-if="error" class="mb-4" :message="error" type="error" show-icon />
      <FormItem label="地区额度" required>
        <div class="grid grid-cols-[minmax(0,1fr)_120px] items-center gap-x-3 gap-y-2">
          <template v-for="allocation in form.allocations" :key="allocation.region">
            <span>{{ allocation.region }}{{ allocation.historical ? '（历史地区）' : '' }}</span>
            <InputNumber
              v-model:value="allocation.quota"
              :min="0"
              :precision="0"
              class="w-full"
              :aria-label="`${allocation.region}额度`"
            />
          </template>
        </div>
      </FormItem>
      <FormItem label="允许创建服务器">
        <Space>
          <Switch
            v-model:checked="form.allowCreate"
            aria-label="允许创建服务器"
            checked-children="开"
            un-checked-children="关"
          />
          <span>{{ form.allowCreate ? '新服务器按已分配额度创建' : '已禁止创建新服务器' }}</span>
        </Space>
      </FormItem>
      <Alert
        v-if="!form.allowCreate"
        class="mb-4"
        type="warning"
        show-icon
        message="关闭后，服务端会拒绝新的服务器创建；现有服务器不受影响。"
      />
      <Button type="primary" html-type="submit" :loading="saving" block>
        {{ saving ? '保存中' : '保存' }}
      </Button>
    </Form>
  </Modal>
</template>
